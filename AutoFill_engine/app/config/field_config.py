FIELD_CONFIG = {
    "company": {"required": True, "source": "user"},
    "product": {"required": True, "source": "user"},
    "country": {"required": True, "source": "user"},
    "production": {"required": True, "source": "user"},
    "expDatetime": {"required": True, "source": "user"},
    "title": {"required": True, "source": "llm"},
    "journalTitle": {"required": True, "source": "llm"},
    "keyAuthor": {"required": True, "source": "llm"},
    "productionNotes": {"required": True, "source": "user"},
    "fileType": {"required": True, "source": "inferred"},
}

QUESTIONS = {
    "company": "Please enter the company name.",
    "product": "Please select the product.",
    "country": "Which country is this for?",
    "production": "What is the production value?",
    "expDatetime": "Please provide the expiry date and time.",
    "productionNotes": "Any production notes for the DocIntel team?",
    "chapter": "Please list the chapter titles in order. You can include file names, for example: doc1.pdf is Chapter 1 titled Introduction.",
}
