from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    root: Path = Path(__file__).resolve().parents[2]
    seed_dir: Path = root / "data" / "seed"
    raw_dir: Path = root / "data" / "raw"
    normalized_dir: Path = root / "data" / "normalized"
    public_dir: Path = root / "data" / "public"
    state_dir: Path = root / "data" / "state"
    cache_dir: Path = root / "cache"

    def ensure_dirs(self) -> None:
        for path in (self.raw_dir, self.normalized_dir, self.public_dir, self.state_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

settings = Settings()
