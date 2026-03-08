---
id: paperless_assistant
name: Paperless Assistant
description: Search, browse, upload, and manage documents in Paperless-ngx.
tasks:
  - paperless_search
  - paperless_get_document
  - paperless_update_document
  - paperless_upload
  - paperless_download
  - paperless_list
  - paperless_manage_metadata
essential_tasks:
  - paperless_search
  - paperless_list
  - paperless_manage_metadata
keywords: ["paperless", "dokument", "dokumente", "rechnung", "rechnungen"]
examples:
  - "Search Paperless for invoices from 2024"
  - "Upload this PDF to Paperless"
  - "Show me recent documents in Paperless"
  - "Update the tags on document 42"
safe_defaults: {}
confirm_before_write:
  - delete documents
requires_permissions: []
---
