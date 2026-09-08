"""
document_registry.py
--------------------
Registry that manages multiple medical coverage policies, discovering their
TOC files, chunk metadata, embeddings, and BM25 indices.
Enables dynamic multi-policy routing and scoped search without hardcoding.
"""

import os
import json
from pathlib import Path


class DocumentRegistry:
    def __init__(self, base_dir: str = None, manifest_file: str = "policies_manifest.json"):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent
        else:
            base_dir = Path(base_dir)
        self.base_dir = base_dir
        self.manifest_file = self.base_dir / manifest_file
        self.documents = {}
        self.scan_and_register()

    def register_document(
        self,
        doc_key: str,
        display_name: str,
        toc_file: str,
        metadata_file: str,
        embeddings_file: str,
        bm25_file: str
    ):
        """Register a policy document and its associated search indices."""
        self.documents[doc_key] = {
            "key": doc_key,
            "display_name": display_name,
            "toc_file": str(toc_file),
            "metadata_file": str(metadata_file),
            "embeddings_file": str(embeddings_file),
            "bm25_file": str(bm25_file)
        }

    def _resolve_path(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        return self.base_dir / p

    def scan_and_register(self):
        """Discover and register all available policy documents dynamically."""
        # 1. Load from policies_manifest.json if available
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                policies = manifest.get("policies", [])
                for pol in policies:
                    doc_key = pol.get("doc_key")
                    display_name = pol.get("display_name", doc_key)
                    toc_file = self._resolve_path(pol.get("toc_file", ""))
                    meta_file = self._resolve_path(pol.get("metadata_file", ""))
                    emb_file = self._resolve_path(pol.get("embeddings_file", ""))
                    bm25_file = self._resolve_path(pol.get("bm25_file", ""))

                    if meta_file.exists() and emb_file.exists():
                        self.register_document(
                            doc_key=doc_key,
                            display_name=display_name,
                            toc_file=str(toc_file),
                            metadata_file=str(meta_file),
                            embeddings_file=str(emb_file),
                            bm25_file=str(bm25_file)
                        )
            except Exception as e:
                print(f"[DocumentRegistry] Error reading manifest {self.manifest_file}: {e}")

        # 2. Dynamic Auto-Discovery: scan for any metadata + embeddings pairs not yet registered
        self._auto_discover_unregistered_policies()

    def _auto_discover_unregistered_policies(self):
        """Scan base directory for policy metadata files and register matching index files."""
        for meta_path in self.base_dir.rglob("*_metadata.json"):
            # Derive base prefix from metadata filename
            stem = meta_path.stem
            prefix = stem[:-9] if stem.endswith("_metadata") else stem
            parent_dir = meta_path.parent

            # Check if already registered
            if any(doc["metadata_file"] == str(meta_path) for doc in self.documents.values()):
                continue

            # Look for matching embeddings and bm25 files
            candidates_emb = [
                parent_dir / f"{prefix}_embeddings.npy",
                self.base_dir / f"{prefix}_embeddings.npy"
            ]
            candidates_bm25 = [
                parent_dir / f"{prefix}_bm25.pkl",
                self.base_dir / f"{prefix}_bm25.pkl",
                self.base_dir / "md" / "bm25" / f"{prefix}_bm25.pkl"
            ]
            candidates_toc = [
                parent_dir / f"{prefix}_toc_output.json",
                self.base_dir / f"{prefix}_toc_output.json",
                self.base_dir / f"{prefix}_toc.json",
                self.base_dir / "md" / f"{prefix}_toc_output.json"
            ]

            emb_file = next((c for c in candidates_emb if c.exists()), None)
            bm25_file = next((c for c in candidates_bm25 if c.exists()), None)
            toc_file = next((c for c in candidates_toc if c.exists()), None)

            if emb_file and emb_file.exists():
                doc_key = prefix
                display_name = prefix.replace("_", " ").title()

                # Attempt to extract nicer display title from TOC if available
                if toc_file and toc_file.exists():
                    try:
                        with open(toc_file, "r", encoding="utf-8") as tf:
                            tdata = json.load(tf)
                            first_title = None
                            for node in tdata.get("flat_toc", []):
                                if node.get("title"):
                                    first_title = node.get("title").strip()
                                    break
                            if first_title:
                                display_name = f"{display_name} ({first_title})"
                    except Exception:
                        pass

                self.register_document(
                    doc_key=doc_key,
                    display_name=display_name,
                    toc_file=str(toc_file) if toc_file else "",
                    metadata_file=str(meta_path),
                    embeddings_file=str(emb_file),
                    bm25_file=str(bm25_file) if bm25_file else ""
                )

    def get_document(self, doc_key: str) -> dict:
        return self.documents.get(doc_key)

    def get_compact_tocs(self, doc_key: str = None) -> str:
        """
        Render a compact text representation of the Table of Contents across
        all registered policies for LLM-based policy and section routing.
        """
        target_keys = [doc_key] if doc_key and doc_key in self.documents else list(self.documents.keys())
        lines = []

        for k in target_keys:
            doc = self.documents[k]
            lines.append(f"=== POLICY DOCUMENT: {doc['display_name']} [Key: {k}] ===")
            toc_file = doc["toc_file"]
            if toc_file and os.path.exists(toc_file):
                try:
                    with open(toc_file, "r", encoding="utf-8") as f:
                        toc_data = json.load(f)
                    flat_toc = toc_data.get("flat_toc", [])
                    for item in flat_toc:
                        t_id = item.get("toc_id")
                        title = item.get("title", "").strip()
                        page = item.get("page")
                        if not t_id or not title:
                            continue
                        level = item.get("heading_level", 1)
                        indent = "  " * max(0, min(level - 1, 3))
                        page_str = f" (p.{page})" if page else ""
                        lines.append(f"{indent}[{t_id}] {title}{page_str}")
                except Exception as e:
                    lines.append(f"  (Error reading TOC: {e})")
            lines.append("")

        return "\n".join(lines)


if __name__ == "__main__":
    registry = DocumentRegistry()
    print("Registered documents:", list(registry.documents.keys()))
    print("\nCompact TOC Preview:")
    print(registry.get_compact_tocs()[:1500] + "\n...")
