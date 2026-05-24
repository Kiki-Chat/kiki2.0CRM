"""queryKnowledgeBase tool.

No knowledge-base store exists yet (PDF/URL ingestion is a later phase), so this
returns the documented graceful "no answer" response, prompting the agent to
take a message or refer to the office.
"""

from app.schemas.tools import QueryKnowledgeBaseRequest


def query_knowledge_base(org_id: str, payload: QueryKnowledgeBaseRequest) -> dict:
    return {
        "success": True,
        "answer": None,
        "message": "Dazu liegen mir keine Informationen vor. Ich kann gern eine "
        "Nachricht aufnehmen oder Sie an das Büro verweisen.",
    }
