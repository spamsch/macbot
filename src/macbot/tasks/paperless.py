"""Tasks: Paperless-ngx Integration

Provides tasks for the agent to interact with a paperless-ngx document management system.
Supports searching, uploading, downloading, and managing documents.

API Documentation: https://docs.paperless-ngx.com/api/
"""

import logging
from pathlib import Path
from typing import Any

import httpx

from macbot.config import settings
from macbot.tasks.base import Task

logger = logging.getLogger(__name__)


def _get_headers() -> dict[str, str]:
    """Get headers for paperless API requests."""
    return {
        "Authorization": f"Token {settings.paperless_api_token}",
        "Accept": "application/json",
    }


def _get_base_url() -> str:
    """Get base URL, ensuring no trailing slash."""
    return settings.paperless_url.rstrip("/")


def _normalize_list(value: Any) -> list[Any]:
    """Ensure value is a list. Handles JSON arrays, comma-separated strings, single values, and lists."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        # Try JSON first: '["Inbox","KV"]' or '[1,2,3]'
        stripped = value.strip()
        if stripped.startswith("["):
            import json
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        # Fall back to comma-separated: "Inbox,KV,Beleg" or "Inbox, KV, Beleg"
        return [item.strip() for item in value.split(",") if item.strip()]
    if value is not None:
        return [value]
    return []


async def _resolve_tags(tags: list[int | str] | str) -> list[int]:
    """Resolve a mixed list of tag IDs (int) and tag names (str) to IDs.

    Accepts a list, a single value, or a comma-separated string.
    Integers and numeric strings are kept as-is. Non-numeric strings are
    looked up via the Paperless API by name (case-insensitive).

    Returns:
        List of resolved integer tag IDs. Unknown names are silently skipped.
    """
    logger.info("_resolve_tags called with: %r (type: %s)", tags, type(tags).__name__)
    items = _normalize_list(tags)
    logger.info("_resolve_tags normalized to: %r", items)
    resolved: list[int] = []
    names_to_resolve: list[str] = []

    for tag in items:
        if isinstance(tag, int):
            resolved.append(tag)
        elif isinstance(tag, str) and tag.isdigit():
            resolved.append(int(tag))
        elif isinstance(tag, str):
            names_to_resolve.append(tag)

    if names_to_resolve:
        logger.info("_resolve_tags looking up names: %r", names_to_resolve)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_get_base_url()}/api/tags/",
                params={"page_size": 200},
                headers=_get_headers(),
            )
            response.raise_for_status()
            all_tags = response.json().get("results", [])

        name_map = {t["name"].lower(): t["id"] for t in all_tags}
        logger.info("_resolve_tags available tags: %r", list(name_map.keys()))
        for name in names_to_resolve:
            tag_id = name_map.get(name.lower())
            if tag_id is not None:
                resolved.append(tag_id)
            else:
                logger.warning("_resolve_tags: tag '%s' not found in Paperless", name)

    return resolved


async def _resolve_resource(
    value: Any, endpoint: str
) -> int | None:
    """Resolve a resource by ID (int/numeric str) or name (str lookup).

    Args:
        value: Integer ID, numeric string, or resource name.
        endpoint: API endpoint, e.g. '/api/correspondents/'.

    Returns:
        Integer ID, or None if unresolvable.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # Strip surrounding quotes from JSON serialization: '"EDEKA"' → 'EDEKA'
        value = value.strip().strip('"').strip("'")
        if value.isdigit():
            return int(value)
        # Look up by name
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_get_base_url()}{endpoint}",
                params={"page_size": 200},
                headers=_get_headers(),
            )
            response.raise_for_status()
            items = response.json().get("results", [])

        name_map = {item["name"].lower(): item["id"] for item in items}
        return name_map.get(value.lower())
    return None


class PaperlessSearchTask(Task):
    """Search documents in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_search"

    @property
    def description(self) -> str:
        return (
            "Search documents in Paperless-ngx. Supports full-text search via 'query' "
            "and filtering by inbox status, tags (IDs or names), correspondent, or document type. "
            "Use is_inbox=True to list inbox documents. Filters can be combined with a query."
        )

    async def execute(
        self,
        query: str = "",
        limit: int = 10,
        is_inbox: bool = False,
        tags: list[int | str] | None = None,
        correspondent_id: int | str | None = None,
        document_type_id: int | str | None = None,
    ) -> dict[str, Any]:
        """Search for documents.

        Args:
            query: Full-text search query (optional if using filters).
            limit: Maximum number of results to return (default: 10).
            is_inbox: If True, only return documents with an inbox tag.
            tags: Filter by tag IDs or names (documents must have all listed tags).
            correspondent_id: Filter by correspondent ID.
            document_type_id: Filter by document type ID.

        Returns:
            Dictionary with search results or error
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
            }

        # Resolve tag names to IDs, correspondent/doc-type names to IDs
        if tags:
            tags = await _resolve_tags(tags)  # type: ignore[assignment]
        correspondent_id = await _resolve_resource(correspondent_id, "/api/correspondents/")
        document_type_id = await _resolve_resource(document_type_id, "/api/document_types/")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params: dict[str, Any] = {"page_size": limit}

                # Parse is:inbox from query string for convenience
                clean_query = query
                if "is:inbox" in clean_query:
                    is_inbox = True
                    clean_query = clean_query.replace("is:inbox", "").strip()

                if clean_query:
                    params["query"] = clean_query

                if is_inbox:
                    params["is_in_inbox"] = "true"

                if tags:
                    params["tags__id__all"] = ",".join(str(t) for t in tags)
                if correspondent_id is not None:
                    params["correspondent__id"] = correspondent_id
                if document_type_id is not None:
                    params["document_type__id"] = document_type_id

                response = await client.get(
                    f"{_get_base_url()}/api/documents/",
                    params=params,
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
                        "custom_fields": doc.get("custom_fields", []),
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
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
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
                        "content": doc.get("content", ""),
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
                        "custom_fields": doc.get("custom_fields", []),
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


class PaperlessUpdateDocumentTask(Task):
    """Update a document in Paperless-ngx."""

    @property
    def name(self) -> str:
        return "paperless_update_document"

    @property
    def description(self) -> str:
        return (
            "Update a document's metadata in Paperless-ngx. "
            "Can change title, created date, tags (list of tag IDs or names — replaces all tags), "
            "correspondent, document type, and custom fields. "
            "For custom_fields pass a list of dicts: [{\"field\": <field_id>, \"value\": <value>}]. "
            "Pass an empty list [] to clear custom fields. "
            "For created, use ISO format: '2023-07-12'."
        )

    async def execute(
        self,
        document_id: int | str,
        title: str | None = None,
        created: str | None = None,
        tags: list[int | str] | None = None,
        correspondent: int | str | None = None,
        document_type: int | str | None = None,
        custom_fields: list[dict[str, Any]] | str | None = None,
    ) -> dict[str, Any]:
        """Update document metadata.

        Args:
            document_id: The document ID to update.
            title: New title (unchanged if not provided).
            created: New created date in ISO format, e.g. '2023-07-12' (unchanged if not provided).
            tags: New list of tag IDs or names (replaces all tags; unchanged if not provided).
            correspondent: New correspondent ID (unchanged if not provided).
            document_type: New document type ID (unchanged if not provided).
            custom_fields: List of custom field values, e.g. [{"field": 1, "value": "42.50"}].

        Returns:
            Dictionary with updated document or error.
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
            }

        # Resolve names to IDs and coerce string IDs to ints
        doc_id = await _resolve_resource(document_id, "/api/documents/")
        document_id = doc_id if doc_id is not None else document_id  # type: ignore[assignment]
        if tags is not None:
            tags = await _resolve_tags(tags)  # type: ignore[assignment]
        correspondent = await _resolve_resource(correspondent, "/api/correspondents/")
        document_type = await _resolve_resource(document_type, "/api/document_types/")

        # Parse custom_fields if passed as JSON string
        if isinstance(custom_fields, str):
            import json
            try:
                custom_fields = json.loads(custom_fields)
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "error": f"custom_fields must be a JSON list, got: {custom_fields[:100]}"}

        patch_data: dict[str, Any] = {}
        if title is not None:
            patch_data["title"] = title
        if created is not None:
            patch_data["created"] = created
        if tags is not None:
            patch_data["tags"] = tags
        if correspondent is not None:
            patch_data["correspondent"] = correspondent
        if document_type is not None:
            patch_data["document_type"] = document_type
        if custom_fields is not None:
            patch_data["custom_fields"] = custom_fields

        if not patch_data:
            return {"success": False, "error": "No fields to update."}

        logger.info("paperless_update_document(%s) patch_data: %r", document_id, patch_data)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.patch(
                    f"{_get_base_url()}/api/documents/{document_id}/",
                    json=patch_data,
                    headers={**_get_headers(), "Content-Type": "application/json"},
                )
                response.raise_for_status()
                doc = response.json()

                result = {
                    "success": True,
                    "_sent": patch_data,
                    "document": {
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "created": doc.get("created"),
                        "tags": doc.get("tags", []),
                        "tag_names": doc.get("tags__name", []),
                        "correspondent": doc.get("correspondent"),
                        "correspondent_name": doc.get("correspondent__name"),
                        "document_type": doc.get("document_type"),
                        "document_type_name": doc.get("document_type__name"),
                        "custom_fields": doc.get("custom_fields", []),
                    },
                }
                logger.info("paperless_update_document(%s) response tags: %r", document_id, doc.get("tags"))
                return result

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
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
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
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
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


class PaperlessListTask(Task):
    """List metadata resources (tags, correspondents, document types, custom fields) in Paperless-ngx."""

    _RESOURCE_CONFIG: dict[str, dict[str, Any]] = {
        "tags": {
            "endpoint": "/api/tags/",
            "fields": ["id", "name", "color", "is_inbox_tag", "document_count"],
        },
        "correspondents": {
            "endpoint": "/api/correspondents/",
            "fields": ["id", "name", "document_count"],
        },
        "document_types": {
            "endpoint": "/api/document_types/",
            "fields": ["id", "name", "document_count"],
        },
        "custom_fields": {
            "endpoint": "/api/custom_fields/",
            "fields": ["id", "name", "data_type"],
        },
    }

    @property
    def name(self) -> str:
        return "paperless_list"

    @property
    def description(self) -> str:
        return (
            "List metadata resources in Paperless-ngx. "
            "Set resource_type to one of: tags, correspondents, document_types, custom_fields."
        )

    async def execute(self, resource_type: str = "tags") -> dict[str, Any]:
        """List a metadata resource.

        Args:
            resource_type: One of 'tags', 'correspondents', 'document_types', 'custom_fields'.

        Returns:
            Dictionary with items or error.
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
            }

        config = self._RESOURCE_CONFIG.get(resource_type)
        if not config:
            return {
                "success": False,
                "error": f"Unknown resource_type '{resource_type}'. Use one of: {', '.join(self._RESOURCE_CONFIG)}",
            }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_get_base_url()}{config['endpoint']}",
                    params={"page_size": 100},
                    headers=_get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                items = []
                for item in data.get("results", []):
                    items.append({f: item.get(f) for f in config["fields"]})

                return {
                    "success": True,
                    "count": data.get("count", 0),
                    resource_type: items,
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


class PaperlessManageMetadataTask(Task):
    """Create or delete metadata resources (tags, correspondents, document types) in Paperless-ngx."""

    _RESOURCE_CONFIG: dict[str, dict[str, Any]] = {
        "tags": {
            "endpoint": "/api/tags/",
            "create_fields": ["name", "color", "is_inbox_tag"],
        },
        "correspondents": {
            "endpoint": "/api/correspondents/",
            "create_fields": ["name"],
        },
        "document_types": {
            "endpoint": "/api/document_types/",
            "create_fields": ["name"],
        },
    }

    @property
    def name(self) -> str:
        return "paperless_manage_metadata"

    @property
    def description(self) -> str:
        return (
            "Create or delete metadata resources in Paperless-ngx. "
            "Supports tags, correspondents, and document_types. "
            "Use action='create' with a name to create a new resource. "
            "Use action='delete' with a resource_id to delete one. "
            "For tags, you can also set color (hex like '#ff0000') and is_inbox_tag."
        )

    async def execute(
        self,
        action: str,
        resource_type: str = "tags",
        resource_id: int | None = None,
        name: str | None = None,
        color: str | None = None,
        is_inbox_tag: bool = False,
    ) -> dict[str, Any]:
        """Create or delete a metadata resource.

        Args:
            action: 'create' or 'delete'.
            resource_type: One of 'tags', 'correspondents', 'document_types'.
            resource_id: ID of the resource to delete (required for delete).
            name: Name for the new resource (required for create).
            color: Hex color for tags, e.g. '#ff0000' (optional, tags only).
            is_inbox_tag: Whether this tag marks inbox documents (optional, tags only).

        Returns:
            Dictionary with created/deleted resource or error.
        """
        if not settings.paperless_url or not settings.paperless_api_token:
            return {
                "success": False,
                "error": "Paperless-ngx not configured. Set MACBOT_PAPERLESS_URL and MACBOT_PAPERLESS_API_TOKEN in Settings or run 'son onboard'.",
            }

        config = self._RESOURCE_CONFIG.get(resource_type)
        if not config:
            return {
                "success": False,
                "error": f"Unknown resource_type '{resource_type}'. Use one of: {', '.join(self._RESOURCE_CONFIG)}",
            }

        if action == "create":
            return await self._create(config, resource_type, name, color, is_inbox_tag)
        elif action == "delete":
            return await self._delete(config, resource_type, resource_id)
        else:
            return {
                "success": False,
                "error": f"Unknown action '{action}'. Use 'create' or 'delete'.",
            }

    async def _create(
        self,
        config: dict[str, Any],
        resource_type: str,
        name: str | None,
        color: str | None,
        is_inbox_tag: bool,
    ) -> dict[str, Any]:
        if not name:
            return {"success": False, "error": "name is required for create."}

        payload: dict[str, Any] = {"name": name}
        if resource_type == "tags":
            if color is not None:
                payload["color"] = color
            if is_inbox_tag:
                payload["is_inbox_tag"] = True

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{_get_base_url()}{config['endpoint']}",
                    json=payload,
                    headers={**_get_headers(), "Content-Type": "application/json"},
                )
                response.raise_for_status()
                item = response.json()

                return {
                    "success": True,
                    "action": "created",
                    resource_type[:-1]: {
                        "id": item.get("id"),
                        "name": item.get("name"),
                    },
                }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {"success": False, "error": f"Connection error: {e}"}

    async def _delete(
        self,
        config: dict[str, Any],
        resource_type: str,
        resource_id: int | None,
    ) -> dict[str, Any]:
        if resource_id is None:
            return {"success": False, "error": "resource_id is required for delete."}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{_get_base_url()}{config['endpoint']}{resource_id}/",
                    headers=_get_headers(),
                )
                response.raise_for_status()

                return {
                    "success": True,
                    "action": "deleted",
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {
                    "success": False,
                    "error": f"{resource_type} with id {resource_id} not found",
                }
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            }
        except httpx.RequestError as e:
            return {"success": False, "error": f"Connection error: {e}"}


def register_paperless_tasks(registry) -> None:
    """Register Paperless-ngx tasks with a registry.

    Args:
        registry: TaskRegistry to register tasks with.
    """
    registry.register(PaperlessSearchTask())
    registry.register(PaperlessGetDocumentTask())
    registry.register(PaperlessUpdateDocumentTask())
    registry.register(PaperlessUploadTask())
    registry.register(PaperlessDownloadTask())
    registry.register(PaperlessListTask())
    registry.register(PaperlessManageMetadataTask())
