---
id: contacts_assistant
name: Contacts Assistant
description: Look up, search, and create contacts in Contacts.app.
apps:
  - Contacts
tasks:
  - search_contacts
  - get_contact
  - create_contact
  - list_contact_groups
essential_tasks: []
examples:
  - "What's Joe's phone number?"
  - "Find contacts at Acme Corp"
  - "Look up Sarah's email address"
  - "Add a new contact for John Smith"
  - "Show me all contact groups"
safe_defaults:
  limit: 20
confirm_before_write:
  - create contact
requires_permissions:
  - Automation:Contacts
---

## Behavior Notes

### Search Strategy
- **Search by name first** — it uses a `whose` clause and is near-instant.
- Fall back to email or phone search only when name search returns nothing or user explicitly provides an email/phone.
- Organization search also uses `whose` (fast).

### Getting Full Contact Details
- Use `search_contacts` to find the person first (returns summary: name, primary email/phone).
- Then use `get_contact` with the exact name to fetch the full card (all emails, phones, addresses, notes, birthday, groups).

### Creating Contacts
- Always confirm the details before creating a new contact.
- `first_name` is required; all other fields are optional.
- Multiple emails and phones can be provided.
- If a group is specified, it must already exist in Contacts.app.

### Groups
- Use `list_contact_groups` to see available groups before assigning contacts.
- Groups cannot be created via automation — they must be created manually in Contacts.app.

### Common Request Patterns
- **"What's X's number?"** → `search_contacts(name="X")` → `get_contact(name="X")`
- **"Find contacts at Acme"** → `search_contacts(organization="Acme")`
- **"Add John Smith"** → confirm details → `create_contact(first_name="John", last_name="Smith", ...)`
- **"Show my groups"** → `list_contact_groups()`
