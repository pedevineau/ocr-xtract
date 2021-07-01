from collections import Counter
from pathlib import Path
from pprint import pprint
from typing import Optional, List, Dict

import numpy as np
from doctr.models import ocr_predictor
from doctr.documents import DocumentFile, Page, Document, Word
from sklearn.feature_extraction import DictVectorizer
from scipy.spatial.distance import cosine
from sklearn.feature_extraction.text import CountVectorizer
import pandas as pd


class PageExtended(Page):
    pass


class WindowTransformer(DictVectorizer):
    def __init__(self, horizontal: int = 3, vertical: int = 3, page_id: Optional[int] = None, line_eps: float = 2):

        # self.document = doctr_doc
        # self.document.pages[0].blocks[0].lines[0].words
        super().__init__(sparse=False)
        self.neighbors = []
        self.n_horizontal = horizontal
        self.n_vertical = vertical
        self.coordinates_sorted_ids = []
        self.page_id = page_id
        self.line_eps = line_eps
        self._features = None
        self._list_same_line_arr = None
        self._list_words_per_page = None
        self._list_words_in_page = []

    def _get_neighbors(self, target_word_idx: int, target_word: Word, page_id: int):
        same_line_indices = self._list_same_line_arr[page_id][target_word_idx].nonzero()[0]
        same_line_words = list(self._list_words_per_page[page_id][same_line_indices])
        same_line_words.append(target_word)
        same_line_words = np.array(same_line_words)
        same_line_x_min = [w.geometry[0][0] for w in same_line_words]

        sorted_points_in_line = np.argsort(same_line_x_min)
        target_word_idx_sorted = np.where(sorted_points_in_line == len(same_line_x_min) - 1)[0][0]
        left_neighbor_points_indices = sorted_points_in_line[
                                       max(0, target_word_idx_sorted - self.n_horizontal):target_word_idx_sorted]
        right_neighbor_points_indices = sorted_points_in_line[
                                        target_word_idx_sorted + 1: target_word_idx_sorted + self.n_horizontal]
        left_neighbor_words = same_line_words[left_neighbor_points_indices]
        right_neighbor_words = same_line_words[right_neighbor_points_indices]
        return {"left": left_neighbor_words, "right": right_neighbor_words}

    def _transform(self, doct_documents: List[Document], **kwargs):
        if not isinstance(doct_documents, list):
            doct_documents = [doct_documents]
        list_array_angle = []
        list_array_distance = []
        for doc in doct_documents:
            for page_id, page in enumerate(doc.pages):
                list_words_in_page = get_list_words_in_page(page)
                list_plain_words_in_page = [word.value for word in list_words_in_page]
                self._list_words_in_page.extend(list_plain_words_in_page)

                vocab = self.vocab
                array_angles = np.zeros((len(vocab), len(list_words_in_page)))  # false value for angle
                array_distances = np.ones((len(vocab), len(list_words_in_page))) * 5  # max distance

                for i, vocab_i in enumerate(vocab):
                    if vocab_i in list_plain_words_in_page:
                        wi_list = [i for i, x in enumerate(list_plain_words_in_page) if x == vocab_i]
                        for wi in wi_list:
                            word_i = list_words_in_page[wi]  # associate the vocab_i to a word that is in the document
                            for j, word_j in enumerate(list_words_in_page):
                                x_i, y_i = word_i.geometry[0]
                                x_j, y_j = word_j.geometry[0]
                                distance = cosine(word_i.geometry[0], word_j.geometry[0])
                                if distance < array_distances[
                                    i, j]:  # in case there are several identical duplicate of vocab i, take the closest
                                    array_angles[i, j] = np.arctan((y_j - y_i) / (x_j - x_i) if (x_j - x_i) != 0 else 0)
                                    array_distances[i, j] = distance
                    else:
                        print(f'--------------vocab------{vocab_i} not in page')

                list_array_angle.append(array_angles)
                list_array_distance.append(array_distances)
        self.array_angle = np.hstack(list_array_angle)
        self.array_distances = np.hstack(list_array_distance)
        self.array = np.concatenate([self.array_angle, self.array_distances])
        self._feature_names = [a + '_angle' for a in self.vocab] + [a + '_distance' for a in self.vocab]

        # TODO : keep the name of the doc and pages in a self.list_doc self.list_pages
        return self.array

    def fit(self, doctr_documents: List[Document], **kwargs):
        # self._get_sorted_coordinates(X)
        # get ALL Words of a page
        if not isinstance(doctr_documents, list):
            doctr_documents = [doctr_documents]
        list_words = []
        for doc in doctr_documents:
            for page_id, page in enumerate(doc.pages):
                list_words.extend(get_list_words_in_page(page))

        # vectorizer = CountVectorizer(min_df=1)
        # vectorizer.fit(list_words)
        #
        # self.vectorizer = vectorizer
        # self.vocab = vectorizer.get_feature_names()
        self.list_word = [word.value for word in list_words]
        self.vocab = [k for k, v in Counter(self.list_word).items() if v >= 2]
        return self

    def transform(self, X: List[Document]):
        return self._transform(X)

    def _get_doctr_docs(self, raw_documents: List[Path]):
        list_doctr_docs = []
        if not hasattr(self, "doctr_model"):
            self.doctr_model = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True)

        for doc in raw_documents:
            if not doc.exists():
                print(f"Doc {doc} could not be found.")
                continue
            res_doctr = None
            try:
                if doc.suffix == "pdf":
                    doc_doctr = DocumentFile.from_pdf(doc)
                else:
                    doc_doctr = DocumentFile.from_images(doc)
                res_doctr = self.doctr_model(doc_doctr, training=False)
            except Exception as e:
                print(f"Could not analyze document {doc}. Error: {e}")
            if res_doctr:
                list_doctr_docs.append(res_doctr)
        return list_doctr_docs

    def fit_transform(self, X: List[Document], **kwargs):
        self.fit(X)
        return self._transform(X)

    @staticmethod
    def _get_neighbors_features(word, neighbors: Dict[str, List[Word]]):
        features = {}
        left_side_words = neighbors["left"]
        right_side_words = neighbors["right"]
        for id_word, word_neighbor in enumerate(left_side_words):
            features[f"w{id_word - len(left_side_words)}:{word_neighbor.value.lower()}"] = 1

        features[f"w:{word.value.lower()}"] = 1

        for id_word, word_neighbor in enumerate(right_side_words):
            features[f"w+{id_word + 1}:{word_neighbor.value.lower()}"] = 1

        return features


class WindowTransformerList(DictVectorizer):
    def __init__(self, horizontal: int = 3, vertical: int = 3, page_id: Optional[int] = None, line_eps: float = 2):
        super().__init__(sparse=False)
        self.neighbors = []
        self.n_horizontal = horizontal
        self.n_vertical = vertical
        self.coordinates_sorted_ids = []
        self.page_id = page_id
        self.line_eps = line_eps
        self._features = None
        self._list_same_line_arr = None
        self._list_words_per_page = None
        self._list_words_in_page = []

    def _transform(self, doct_documents: pd.DataFrame, **kwargs):
        list_array_angle = []
        list_array_distance = []
        for doc in doct_documents['document_name'].unique():
            for page_id, page in enumerate(doct_documents[doct_documents['document_name'] == doc]['page_id'].unique()):
                df = doct_documents[(doct_documents['document_name'] == doc) & (doct_documents['page_id'] == page)]
                list_plain_words_in_page = df['word'].to_list()
                self._list_words_in_page.extend(list_plain_words_in_page)
                vocab = self.vocab
                array_angles = np.zeros((len(vocab), len(list_plain_words_in_page)))  # false value for angle
                array_distances = np.ones((len(vocab), len(list_plain_words_in_page))) * 5  # max distance

                for i, vocab_i in enumerate(vocab):
                    if vocab_i in list_plain_words_in_page:
                        wi_list = [i for i, x in enumerate(list_plain_words_in_page) if x == vocab_i]
                        for wi in wi_list:
                            for j, word_j in enumerate(list_plain_words_in_page):
                                x_i, y_i = df.iloc[wi]['min_x'], df.iloc[wi]['min_y']
                                x_j, y_j = df.iloc[j]['min_x'], df.iloc[j]['min_y']
                                distance = cosine((x_i, y_i), (x_j, y_j))
                                if distance < array_distances[
                                    i, j]:  # in case there are several identical duplicate of vocab i, take the closest
                                    array_angles[i, j] = np.arctan((y_j - y_i) / (x_j - x_i) if (x_j - x_i) != 0 else 0)
                                    array_distances[i, j] = distance
                    else:
                        print(f'--------------vocab------{vocab_i} not in page')

                list_array_angle.append(array_angles)
                list_array_distance.append(array_distances)
        self.array_angle = np.hstack(list_array_angle)
        self.array_distances = np.hstack(list_array_distance)
        self.array = np.concatenate([self.array_angle, self.array_distances])
        self._feature_names = [str(a) + '_angle' for a in self.vocab] + [str(a)  + '_distance' for a in self.vocab]

        # TODO : keep the name of the doc and pages in a self.list_doc self.list_pages
        return self.array

    def fit(self, doctr_documents: pd.DataFrame, **kwargs):
        self.list_words = doctr_documents['word'].to_list()

        # vectorizer = CountVectorizer(min_df=1)
        # vectorizer.fit(list_words)
        #
        # self.vectorizer = vectorizer
        # self.vocab = vectorizer.get_feature_names()
        self.vocab = [k for k, v in Counter(self.list_words).items() if v >= 2]
        return self

    def transform(self, X: List[Document]):
        return self._transform(X)

    def _get_doctr_docs(self, raw_documents: List[Path]):
        list_doctr_docs = []
        if not hasattr(self, "doctr_model"):
            self.doctr_model = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True)

        for doc in raw_documents:
            if not doc.exists():
                print(f"Doc {doc} could not be found.")
                continue
            res_doctr = None
            try:
                if doc.suffix == "pdf":
                    doc_doctr = DocumentFile.from_pdf(doc)
                else:
                    doc_doctr = DocumentFile.from_images(doc)
                res_doctr = self.doctr_model(doc_doctr, training=False)
            except Exception as e:
                print(f"Could not analyze document {doc}. Error: {e}")
            if res_doctr:
                list_doctr_docs.append(res_doctr)
        return list_doctr_docs

    def fit_transform(self, X: List[Document], **kwargs):
        self.fit(X)
        return self._transform(X)

    @staticmethod
    def _get_neighbors_features(word, neighbors: Dict[str, List[Word]]):
        features = {}
        left_side_words = neighbors["left"]
        right_side_words = neighbors["right"]
        for id_word, word_neighbor in enumerate(left_side_words):
            features[f"w{id_word - len(left_side_words)}:{word_neighbor.value.lower()}"] = 1

        features[f"w:{word.value.lower()}"] = 1

        for id_word, word_neighbor in enumerate(right_side_words):
            features[f"w+{id_word + 1}:{word_neighbor.value.lower()}"] = 1

        return features


def extract_words(doctr_result: dict):
    words_dict = []
    for page in doctr_result["pages"]:
        words_dict.append(page["blocks"][0]["lines"][0]["words"])

    return words_dict


def get_doctr_info(img_path: Path) -> Document:
    model = ocr_predictor(det_arch='db_resnet50', reco_arch='crnn_vgg16_bn', pretrained=True)
    doc = DocumentFile.from_images(img_path)
    result = model(doc, training=False)
    # result.show(doc)
    return result


def get_list_words_in_page(page: Document):
    list_words_in_page = []
    for block in page.blocks:
        for line in block.lines:
            list_words_in_page.extend(line.words)
    return list_words_in_page
