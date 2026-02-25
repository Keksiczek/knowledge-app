"""
knowledge_app.py - A simple knowledge base application for storing and retrieving notes.
"""

notes = {}


def add_note(key, content):
    """Add a note to the knowledge base."""
    notes[key] = content


def get_note(key):
    """Retrieve a note from the knowledge base by key."""
    return notes.get(key)


def search_notes(query):
    """Search notes by keyword in key or content."""
    query_lower = query.lower()
    return {
        key: content
        for key, content in notes.items()
        if query_lower in key.lower() or query_lower in content.lower()
    }


def list_notes():
    """Return all note keys."""
    return list(notes.keys())
