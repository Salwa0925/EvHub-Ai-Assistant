import logging
from .base import BaseExporter
from ..utils import safe_filename, write_json

log = logging.getLogger(__name__)

class KnowledgeBaseExporter(BaseExporter):
    """
    Exports knowledge base articles as raw JSON.
    """

    def __init__(self, client, adapter, export_dir: str = "odoo_knowledge_export", published_only: bool = True):
        super().__init__(client, adapter, export_dir)
        self.published_only = published_only

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Knowledge Base articles...")

        domain = [("is_published", "=", True)] if self.published_only else []
        articles = self.client.execute(
            "knowledge.article", "search_read",
            domain=domain,
            fields=["name", "body", "parent_id", "write_date", "create_date", "is_published"],
        )

        if not articles:
            log.info("No articles found.")
            return

        log.info(f"Found {len(articles)} articles.")

        for article in articles:
            self._export_article(article)

        log.info(f"Knowledge base export complete → {self.export_dir}")

    def _export_article(self, article: dict) -> None:
        article_id = article["id"]
        title = article.get("name", f"Article_{article_id}")
        article_dir = self.export_dir / f"{article_id}_{safe_filename(title)}"
        article_dir.mkdir(exist_ok=True)

        clean_article = self.adapter.adapt_record(article)
        write_json(article_dir / "metadata.json", clean_article)
        log.info(f"  -> Saved: {title}")
