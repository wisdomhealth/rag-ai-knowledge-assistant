from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / '.env')


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = ''
    google_drive_folder_ids: tuple[str, ...] = ()
    google_oauth_credentials_file: Path = Path('credentials.json')
    google_oauth_token_file: Path = Path('token.json')
    openai_embedding_model: str = 'text-embedding-3-small'
    embedding_dimensions: int = 1536
    openai_chat_model: str = 'gpt-4o-mini'
    vector_store_dir: Path = Path('data/chroma_v2')
    chroma_collection: str = 'google_drive_llama_v1'
    chunk_size: int = 768
    chunk_overlap: int = 100
    retrieval_top_k: int = 5
    embedding_batch_size: int = 64
    context_max_chars: int = 16000
    history_max_turns: int = 6
    history_max_chars: int = 8000
    request_timeout: float = 90
    max_output_tokens: int = 2000
    session_db: Path = Path('data/sessions.sqlite3')
    session_ttl_seconds: int = 604800
    cookie_secure: bool = False
    api_basic_auth_username: str | None = None
    api_basic_auth_password: str | None = None

    def __post_init__(self):
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError('CHUNK_OVERLAP must be nonnegative and smaller than CHUNK_SIZE')
        for name in ('embedding_dimensions', 'retrieval_top_k', 'embedding_batch_size', 'context_max_chars',
                     'history_max_turns', 'history_max_chars', 'request_timeout', 'max_output_tokens', 'session_ttl_seconds'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        if bool(self.api_basic_auth_username) != bool(self.api_basic_auth_password):
            raise ValueError('Basic Auth username and password must both be configured')

    @property
    def auth_enabled(self):
        return bool(self.api_basic_auth_username and self.api_basic_auth_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    defaults = Settings()
    values = {}
    aliases = {'embedding_dimensions': 'OPENAI_EMBEDDING_DIMENSIONS'}
    for name in defaults.__dataclass_fields__:
        if name == 'google_drive_folder_ids':
            values[name] = tuple(v.strip() for v in os.getenv('GOOGLE_DRIVE_FOLDER_ID', '').split(',') if v.strip())
            continue
        raw = os.getenv(aliases.get(name, name.upper()))
        if raw is None:
            continue
        default = getattr(defaults, name)
        if isinstance(default, bool):
            if raw.lower() not in ('true', 'false', '1', '0'):
                raise ValueError(f'{name} must be true or false')
            values[name] = raw.lower() in ('true', '1')
        elif isinstance(default, Path):
            values[name] = Path(raw)
        elif isinstance(default, (int, float)):
            values[name] = type(default)(raw)
        else:
            values[name] = raw
    return Settings(**values)
