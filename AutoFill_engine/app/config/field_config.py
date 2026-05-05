FIELD_CONFIG = {
    "company": {"required": True, "source": "user"},
    "product": {"required": True, "source": "user"},
    "country": {"required": True, "source": "user"},
    "production": {"required": True, "source": "user"},
    "expDatetime": {"required": True, "source": "user"},
    "productionNotes": {"required": True, "source": "user"},
    "title": {"required": True, "source": "llm"},
    "keyAuthor": {"required": True, "source": "llm"},
    "fileType": {"required": True, "source": "inferred"},
}

QUESTIONS = {
    "company": "Please enter the company name.",
    "product": "Please select the product.",
    "country": "Which country is this for?",
    "production": "What is the production value?",
    "expDatetime": "Please provide expiry date and time.",
    "productionNotes": "Any production notes for the DocIntel team?",
    "chapter": "Please provide chapter titles for all uploaded files in order or with file names.",
    "missing_documents": "You provided chapter titles but forgot to upload the documents. Please upload them!",
}
