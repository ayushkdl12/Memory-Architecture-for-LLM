"""Pluggable vector store.

Default implementation is a simple NumPy cosine-similarity store persisted to
disk (a lean stand-in for FAISS). A ChromaDB backend is provided and is chosen
automatically when `chromadb` is installed and VECTOR_STORE_PROVIDER=chroma.
"""
from __future__ import annotations

import json
import math
import os
import uuid

import numpy as np

from .services.llm import LLMService


class VectorStore:
    def upsert(self, memory_id: str, content: str, metadata: dict) -> None: ...
    def delete(self, memory_id: str) -> None:
        raise NotImplementedError

    def query(self, embedding: list[float], top_k: int) -> list[dict]:
        raise NotImplementedError


class NumpyVectorStore(VectorStore):
    """In-memory + on-disk cosine-similarity store (small scale: <= 5k atoms)."""

    def __init__(self, directory: str, llm: LLMService):
        self.directory = directory
        self.llm = llm
        os.makedirs(directory, exist_ok=True)
        self._data_path = os.path.join(directory, "records.json")
        self._matrix_path = os.path.join(directory, "matrix.npy")
        self.records: list[dict] = self._load_records()
        self.matrix = self._load_matrix()

    # -- persistence --------------------------------------------------------
    def _load_records(self) -> list[dict]:
        if os.path.exists(self._data_path):
            with open(self._data_path) as f:
                return json.load(f)
        return []

    def _load_matrix(self) -> np.ndarray | None:
        if os.path.exists(self._matrix_path):
            return np.load(self._matrix_path).astype(np.float32)
        return None

    def flush(self):
        with open(self._data_path, "w") as f:
            json.dump(self.records, f)
        if self.matrix is not None and len(self.records):
            np.save(self._matrix_path, self.matrix)
        elif os.path.exists(self._matrix_path):
            os.remove(self._matrix_path)

    # -- ops ------------------------------------------------------------------
    def upsert(self, memory_id: str, content: str, metadata: dict) -> None:
        vec = self.llm.embed([content])[0]
        idx = next(
            (i for i, r in enumerate(self.records) if r["memory_id"] == memory_id),
            None,
        )
        if idx is None:
            self.records.append(
                {
                    "memory_id": memory_id,
                    "content": content,
                    "metadata": metadata,
                    "vector": vec,
                }
            )
        else:
            self.records[idx]["content"] = content
            self.records[idx]["metadata"] = metadata
            self.records[idx]["vector"] = vec
        self._rebuild_matrix()

    def delete(self, memory_id: str) -> None:
        self.records = [r for r in self.records if r["memory_id"] != memory_id]
        self._rebuild_matrix()

    def _rebuild_matrix(self):
        if not self.records:
            self.matrix = None
        else:
            self.matrix = np.array([r["vector"] for r in self.records], dtype=np.float32)
        self.flush()

    def query(self, embedding: list[float], top_k: int) -> list[dict]:
        if not self.records:
            return []
        q = np.array(embedding, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        q = q / qn
        norms = np.linalg.norm(self.matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        rows = self.matrix / norms
        scores = rows @ q
        order = np.argsort(-scores)[: min(top_k, len(self.records))]
        return [
            {
                "memory_id": self.records[i]["memory_id"],
                "content": self.records[i]["content"],
                "metadata": self.records[i]["metadata"],
                "score": float(scores[i]),
            }
            for i in order
        ]


class ChromaVectorStore(VectorStore):
    def __init__(self, directory: str, llm: LLMService):
        import chromadb  # imported lazily so numpy path needs no chromadb

        self.llm = llm
        self.client = chromadb.PersistentClient(path=directory)
        self.collection = self.client.get_or_create_collection(
            name="memory_atoms"
        )

    def upsert(self, memory_id: str, content: str, metadata: dict) -> None:
        e = self.llm.embed([content])[0]
        self.collection.upsert(
            ids=[memory_id],
            embeddings=[e],
            documents=[content],
            metadatas=[metadata],
        )

    def delete(self, memory_id: str) -> None:
        try:
            self.collection.delete(ids=[memory_id])
        except Exception:
            pass

    def query(self, embedding: list[float], top_k: int) -> list[dict]:
        e = embedding if embedding else self.llm.embed([""])[0]
        res = self.collection.query(
            query_embeddings=[e], n_results=min(top_k, 1000)
        )
        ids = res["ids"][0]
        metas = res["metadatas"][0]
        docs = res["documents"][0]
        dists = res["distances"][0]
        return [
            {
                "id": ids[i],
                "content": docs[i],
                "metadata": metas[i],
                "score": float(-dists[i]),  # higher = better
            }
            for i in range(len(ids))
        ]


def build_vector_store(provider: str, directory: str, llm: LLMService) -> VectorStore:
    if provider == "chroma":
        try:
            return ChromaVectorStore(directory, llm)
        except Exception:
            pass  # fall back to numpy
    return NumpyVectorStore(directory, llm)