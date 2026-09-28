"""Зонтичные термины — общий словарь для обоих способов выделения кандидатов.

Лежит отдельным модулем, потому что нужен и частотному способу в
`src.pipeline`, и проверке названий от языковой модели в
`src.collect.candidates`, а тащить друг друга они не могут: пайплайн уже
импортирует candidates.

Смысл словаря. Эти слова называют область целиком, а не технологию внутри
неё. «Machine learning» не может быть слабым сигналом в 2026 году, и
«кибербезопасность» по запросу про кибербезопасность — это тема запроса,
а не находка.
"""

from __future__ import annotations

GENERIC = {
    "artificial", "intelligence", "machine", "learning", "deep", "neural",
    "network", "networks", "model", "models", "algorithm", "algorithms",
    "technology", "technologies", "emerging", "digital", "smart", "advanced",
    "security", "cyber", "cybersecurity", "privacy", "safety", "protection",
    "management", "detection", "analysis", "analytics", "computing",
    "software", "hardware", "platform", "service", "services", "industry",
    "industrial", "financial", "finance", "robot", "robotics", "edge",
    "generative", "language", "large", "llm", "llms", "foundation",
    # Слова самой задачи «найти угрозу»: по запросу про кибербезопасность
    # «risk assessment» и «threat detection» — это пересказ темы. В прогоне
    # они дали кандидатов «Оценка рисков» и «Киберриск».
    "risk", "risks", "assessment", "threat", "threats", "attack",
    "attacks", "cyberattack", "cyberattacks", "intrusion", "anomaly",
    "anomalies", "monitoring", "response", "defense", "defence",
    "real", "time", "enhancing", "improving", "leveraging",
    # Добавлено после прогона с GigaChat 28.09: такие названия проходили.
    "weak", "signal", "signals", "data", "cloud", "environment",
    "environments", "iot", "internet", "things", "countermeasures",
    "processing", "natural", "optimization", "driven", "methods",
    "applications", "application", "medical", "healthcare", "practice",
    "architecture", "architectures", "review", "survey", "systematic",
    "comprehensive", "solutions", "solution", "efficient", "effective",
    # Те же слова по-русски: названия от модели приходят на русском, и без
    # них «искусственный интеллект в кибербезопасности» проходит фильтр.
    "искусственный", "интеллект", "интеллекта", "машинное", "обучение",
    "обучения", "нейронные", "нейросети", "сети", "сеть", "модель", "модели",
    "алгоритм", "алгоритмы", "технология", "технологии", "цифровой",
    "цифровые", "умный", "умные", "безопасность", "безопасности",
    "кибербезопасность", "кибербезопасности", "кибер", "киберугрозы",
    "киберугроз", "защита", "защиты", "приватность", "конфиденциальность",
    "управление", "управления", "обнаружение", "обнаружения", "анализ",
    "аналитика", "вычисления", "вычислений", "платформа", "сервис",
    "промышленный", "промышленная", "финансовый", "робот", "робототехника",
    "генеративный", "языковые", "большие", "риск", "риски", "рисков",
    "оценка", "оценки", "угроза", "угрозы", "угроз", "данные", "данных",
    "система", "системы", "решение", "решения", "подход", "подходы",
    "метод", "методы", "реальном", "времени",
    "слабые", "сигналы", "сигналов", "сигнал", "ии", "облачных", "облачные",
    "сред", "среды", "обработка", "обработки", "естественного", "языка",
    "меры", "противодействия", "методы", "оптимизация", "оптимизации",
    "медицине", "применение", "применения", "iot",
    "архитектура", "архитектуры", "обзор", "эффективного", "эффективная",
    "использованием", "использования", "основе", "помощью", "ai-driven",
    "ai-based", "ai-powered", "ml-based",
}
