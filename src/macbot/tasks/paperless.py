"""Tasks: Paperless-ngx Integration

Provides tasks for the agent to interact with a paperless-ngx document management system.
Supports searching, uploading, downloading, and managing documents.

API Documentation: https://docs.paperless-ngx.com/api/
"""

from pathlib import Path
from typing import Any

import httpx

from macbot.config import settings
from macbot.tasks.base import Task


def _get_headers() -> dict[str, str]:
    """Get headers for paperless API requests."""
    return {
        "Authorization": f"Token {settings.paperless_api_token}",
        "Accept": "application/json",
    }


def _get_base_url() -> str:
    """Get base URL, ensuring no trailing slash."""
    return settings.paperless_url.rstrip("/")


class PaperlessSearchTask(Task):
    """Search documents in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_search"

    @property
    def description(self) -> str:
        return (
            "Search documents in Paperless-ngx by full-text query. "
            "Returns matching documents with title, correspondent, tags, and dates."
        )

    async def execute(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search for documents.

        Args:
            query: Full-text search query
            limit: Maximum number of results to return (default: 10)

        Returns:
            Dictionary with search results or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}/api/documents/",
                    params={"query": query, "page_size": limit},
                    headers=_get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                documents = []
                for doc in data.get("results", []):
                    documents.append({
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "correspondent": doc.get("correspondent"),
                        "correspondent_name": doc.get("correspondent__name"),
                        "tags": doc.get("tags", []),
                        "tag_names": doc.get("tags__name", []),
                        "document_type": doc.get("document_type"),
                        "document_type_name": doc.get("document_type__name"),
                        "created": doc.get("created"),
                        "added": doc.get("added"),
                        "archive_serial_number": doc.get("archive_serial_number"),
                    })

                return {
                    "success": True,
                    "count": data.get("count", 0),
                    "documents": documents,
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessGetDocumentTask(Task):
    """Get details of a specific document."""

    @property
    def name(self) -> str:
        return "paperless_get_document"

    @property
    def description(self) -> str:
        return (
            "Get full details of a document by ID, including content preview. "
            "Use after searching to get more information about a specific document."
        )

    async def execute(self, document_id: int) -> dict[str, Any]:
        """Get document details.

        Args:
            document_id: The document ID

        Returns:
            Dictionary with document details or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}/api/documents/{document_id}/",
                    headers=_get_headers(),
                )
                response.raise_for_status()
                doc = response.json()

                return {
                    "success": True,
                    "document": {
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "content": doc.get("content", "")[:2000],  # Limit content preview
                        "correspondent": doc.get("correspondent"),
                        "correspondent_name": doc.get("correspondent__name"),
                        "tags": doc.get("tags", []),
                        "tag_names": doc.get("tags__name", []),
                        "document_type": doc.get("document_type"),
                        "document_type_name": doc.get("document_type__name"),
                        "created": doc.get("created"),
                        "added": doc.get("added"),
                        "modified": doc.get("modified"),
                        "archive_serial_number": doc.get("archive_serial_number"),
                        "original_file_name": doc.get("original_file_name"),
                    },
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Document {document_id} not found",
                }
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessUploadTask(Task):
    """Upload a document to Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_upload"

    @property
    def description(self) -> str:
        return (
            "Upload a document from a local file path to Paperless-ngx. "
            "Returns a task UUID to track upload progress. "
            "Optionally specify title, correspondent, document_type, and tags."
        )

    async def execute(
        self,
        file_path: str,
        title: str | None = None,
        correspondent: int | None = None,
        document_type: int | None = None,
        tags: list[int] | None = None,
    ) -> dict[str, Any]:
        """Upload a document.

        Args:
            file_path: Path to the file to upload
            title: Optional title for the document
            correspondent: Optional correspondent ID
            document_type: Optional document type ID
            tags: Optional list of tag IDs

        Returns:
            Dictionary with task UUID or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        path = Path(file_path).expanduser()
        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
            }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Prepare multipart form data
                files = {"document": (path.name, path.read_bytes())}
                data = {}

                if title:
                    data["title"] = title
                if correspondent is not None:
                    data["correspondent"] = str(correspondent)
                if document_type is not None:
                    data["document_type"] = str(document_type)
                if tags:
                    data["tags"] = ",".join(str(t) for t in tags)

                response = await client.post(
                    f"{_get_base_url()}/api/documents/post_document/",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Token {settings.paperless_api_token}"},
                )
                response.raise_for_status()

                # The response contains a task UUID
                task_id = response.text.strip().strip('"')

                return {
                    "success": True,
                    "task_id": task_id,
                    "message": f"Document uploaded. Task ID: {task_id}",
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessDownloadTask(Task):
    """Download a document from Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_download"

    @property
    def description(self) -> str:
        return (
            "Download the original document file from Paperless-ngx. "
            "Specify an output path or defaults to ~/Downloads."
        )

    async def execute(
        self,
        document_id: int,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Download a document.

        Args:
            document_id: The document ID to download
            output_path: Optional output file path (defaults to ~/Downloads)

        Returns:
            Dictionary with file path or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # First get document info to know the filename
                info_response = await client.get(
                    f"{_get_base_url()}/api/documents/{document_id}/",
                    headers=_get_headers(),
                )
                info_response.raise_for_status()
                doc_info = info_response.json()

                original_name = doc_info.get("original_file_name", f"document_{document_id}.pdf")

                # Download the original file
                response = await client.get(
                    f"{_get_base_url()}/api/documents/{document_id}/download/",
                    headers=_get_headers(),
                )
                response.raise_for_status()

                # Determine output path
                if output_path:
                    out = Path(output_path).expanduser()
                    if out.is_dir():
                        out = out / original_name
                else:
                    out = Path.home() / "Downloads" / original_name

                # Ensure parent directory exists
                out.parent.mkdir(parents=True, exist_ok=True)

                # Write file
                out.write_bytes(response.content)

                return {
                    "success": True,
                    "path": str(out),
                    "message": f"Downloaded to {out}",
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {
                    "success": False,
                    "error": f"Document {document_id} not found",
                }
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessListTagsTask(Task):
    """List available tags in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_list_tags"

    @property
    def description(self) -> str:
        return "List all available tags in Paperless-ngx with their IDs and names."

    async def execute(self) -> dict[str, Any]:
        """List tags.

        Returns:
            Dictionary with tags or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}/api/tags/",
                    headers=_get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                tags = []
                for tag in data.get("results", []):
                    tags.append({
                        "id": tag.get("id"),
                        "name": tag.get("name"),
                        "color": tag.get("color"),
                        "document_count": tag.get("document_count"),
                    })

                return {
                    "success": True,
                    "count": data.get("count", 0),
                    "tags": tags,
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessListCorrespondentsTask(Task):
    """List available correspondents in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_list_correspondents"

    @property
    def description(self) -> str:
        return "List all correspondents in Paperless-ngx with their IDs and names."

    async def execute(self) -> dict[str, Any]:
        """List correspondents.

        Returns:
            Dictionary with correspondents or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}/api/correspondents/",
                    headers=_get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                correspondents = []
                for corr in data.get("results", []):
                    correspondents.append({
                        "id": corr.get("id"),
                        "name": corr.get("name"),
                        "document_count": corr.get("document_count"),
                    })

                return {
                    "success": True,
                    "count": data.get("count", 0),
                    "correspondents": correspondents,
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


class PaperlessListDocumentTypesTask(Task):
    """List available document types in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_list_document_types"

    @property
    def description(self) -> str:
        return "List all document types in Paperless-ngx with their IDs and names."

    async def execute(self) -> dict[str, Any]:
        """List document types.

        Returns:
            Dictionary with document types or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Run 'macbot onboard' to set up.",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}/api/document_types/",
                    headers=_get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                doc_types = []
                for dt in data.get("results", []):
                    doc_types.append({
                        "id": dt.get("id"),
                        "name": dt.get("name"),
                        "document_count": dt.get("document_count"),
                    })

                return {
                    "success": True,
                    "count": data.get("count", 0),
                    "document_types": doc_types,
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection error: {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {e}",
            }


def register_paperless_tasks(registry) -> None:
    """Register Paperless-ngx tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(PaperlessSearchTask())
    registry.register(PaperlessGetDocumentTask())
    registry.register(PaperlessUploadTask())
    registry.register(PaperlessDownloadTask())
    registry.register(PaperlessListTagsTask())
    registry.register(PaperlessListCorrespondentsTask())
    registry.register(PaperlessListDocumentTypesTask())
