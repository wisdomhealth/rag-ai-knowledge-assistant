"""Page-aware LlamaIndex nodes. No embedding or model calls here."""
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from app.services.models import DocumentPage
from app.utils.text_cleaner import clean_text


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build_nodes(pages: list[DocumentPage], chunk_size: int, chunk_overlap: int):
    # Explicit sentence regex avoids runtime NLTK downloads; token sizing is tiktoken.
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                                chunking_tokenizer_fn=lambda text: re.findall(r'[^。！？.!?]+[。！？.!?]*\s*', text),
                                include_prev_next_rel=False)
    grouped = defaultdict(list)
    for page in pages:
        grouped[page.file_id].append(page)
    result = []
    config = f'sentence-v1:{chunk_size}:{chunk_overlap}'
    for file_id, file_pages in grouped.items():
        version = digest(config + json.dumps([asdict(p) for p in file_pages], sort_keys=True, ensure_ascii=False))
        index = 0
        for page in file_pages:
            text = clean_text(page.text)
            if not text:
                continue
            metadata = dict(file_id=file_id, file_name=page.file_name, source_link=page.source_link,
                            page_number=page.page_number or 0, version=version, chunk_version=config)
            doc = Document(text=text, id_=digest(f'{file_id}:{version}:{page.page_number}'), metadata=metadata,
                           excluded_embed_metadata_keys=list(metadata), excluded_llm_metadata_keys=list(metadata))
            for node in splitter.get_nodes_from_documents([doc]):
                content_hash = digest(node.text)
                node.id_ = digest(f'{file_id}:{version}:{index}:{content_hash}')
                node.metadata.update(chunk_id=node.id_, chunk_index=index, content_hash=content_hash)
                node.excluded_embed_metadata_keys = list(node.metadata)
                node.excluded_llm_metadata_keys = list(node.metadata)
                result.append(node)
                index += 1
    return result
