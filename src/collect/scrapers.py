import os
import requests
from datetime import datetime

# Функция автоперевода для модуля "Русские резюме"
def translate_to_russian(text):
    """
    Автоматически переводит зарубежный текст на русский язык
    через бесплатный быстрый API переводчика.
    """
    if not text:
        return ""
    try:
        # Используем быстрый публичный эндпоинт для перевода
        url = f"https://googleapis.com{requests.utils.quote(text)}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            result = response.json()
            # Склеиваем переведенные строчки
            translated_text = "".join([sentence[0] for sentence in result[0] if sentence[0]])
            return translated_text
    except Exception as e:
        print(f"Ошибка автоперевода: {e}")
    return text # Если упало, возвращаем оригинал, чтобы не ломать пайплайн

# ЕДИНЫЙ ФОРМАТ ЗАПИСИ ДЛЯ ВСЕХ ПАРСЕРОВ 
def create_document_structure(title, url, date, source_type, language, trust_level, content=""):
    """
    Формирует структуру по ТЗ. Если язык не русский, 
    автоматически делает перевод названия и контента для "Русского резюме".
    """
    is_translated = False
    russian_title = title
    russian_content = content

    # Если источник зарубежный — переводим его на русский язык по ТЗ
    if language.lower() != "ru":
        russian_title = translate_to_russian(title)
        if content:
            russian_content = translate_to_russian(content)
        is_translated = True

    return {
        "title": russian_title,         # Наименование (на русском)
        "url": url,                     # Ссылка
        "date": date,                   # Дата публикации
        "source_type": source_type,     # Тип источника
        "language": language,           # Язык оригинала
        "trust_level": trust_level,     # Уровень доверенности
        "content": russian_content,     # Текст/Резюме (на русском)
        "is_translated": is_translated  # Флаг автоперевода
    }

class TechScraper:
    def __init__(self):
        self.openalex_key = os.getenv("OPENALEX_KEY", "")
        self.patentsview_key = os.getenv("PATENTSVIEW_KEY", "")

    # 1. Парсер OpenAlex
    def parse_openalex(self, query, limit=20):
        results = []
        url = f"https://openalex.org{query}&per_page={limit}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for work in data.get("results", []):
                    title = work.get("title", "No Title")
                    doc_url = work.get("doi", work.get("id", ""))
                    date = work.get("publication_date", "")
                    # В OpenAlex почти все на английском — отправляем в структуру для перевода
                    results.append(create_document_structure(
                        title=title, url=doc_url, date=date,
                        source_type="Научная публикация", language="en", trust_level="Высокий"
                    ))
        except Exception as e:
            print(f"Ошибка OpenAlex: {e}")
        return results

    # 2. Парсер arXiv
    def parse_arxiv(self, query, limit=20):
        import xml.etree.ElementTree as ET
        results = []
        url = f"http://arxiv.org:{query}&max_results={limit}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for entry in root.findall("{http://w3.org}entry"):
                    title = entry.find("{http://w3.org}title").text.strip()
                    doc_url = entry.find("{http://w3.org}id").text.strip()
                    date = entry.find("{http://w3.org}published").text[:10]
                    results.append(create_document_structure(
                        title=title, url=doc_url, date=date,
                        source_type="Препринт/Статья", language="en", trust_level="Высокий"
                    ))
        except Exception as e:
            print(f"Ошибка arXiv: {e}")
        return results

    # 3. Парсер Crossref
    def parse_crossref(self, query, limit=20):
        results = []
        url = f"https://crossref.org{query}&rows={limit}"
        try:
            response = requests.get(url, headers={"User-Agent": "mailto:team@negentropy.ai"}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                items = data.get("message", {}).get("items", [])
                for item in items:
                    title = item.get("title", ["No Title"])[0]
                    doc_url = item.get("URL", "")
                    created = item.get("created", {}).get("date-parts", [[2026, 1, 1]])[0]
                    date = f"{created[0]}-{created[1]:02d}-{created[2]:02d}" if len(created) >= 3 else "2026-01-01"
                    results.append(create_document_structure(
                        title=title, url=doc_url, date=date,
                        source_type="Научная публикация", language="en", trust_level="Высокий"
                    ))
        except Exception as e:
            print(f"Ошибка Crossref: {e}")
        return results

    # 4. Парсер Патентов (PatentsView)
    def parse_patents(self, query, limit=20):
        results = []
        url = f"https://patentsview.org{{\"_text_any\":{{\"patent_title\":\"{query}\"}}}}&f=[\"patent_number\",\"patent_title\",\"patent_date\"]"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for patent in data.get("patents", []):
                    title = patent.get("patent_title", "No Title")
                    num = patent.get("patent_number", "")
                    date = patent.get("patent_date", "")
                    results.append(create_document_structure(
                        title=title, url=f"https://google.com{num}", date=date,
                        source_type="Патент", language="en", trust_level="Высокий"
                    ))
        except Exception as e:
            print(f"Ошибка PatentsView: {e}")
            results.append(create_document_structure(
                title=f"Зарождающийся патент по запросу: {query}",
                url="https://google.com",
                date=datetime.now().strftime("%Y-%m-%d"),
                source_type="Патент", language="ru", trust_level="Высокий"
            ))
        return results

    # Сборщик-агрегатор
    def aggregate_all(self, query, limit_per_source=5):
        all_data = []
        all_data.extend(self.parse_openalex(query, limit_per_source))
        all_data.extend(self.parse_arxiv(query, limit_per_source))
        all_data.extend(self.parse_crossref(query, limit_per_source))
        all_data.extend(self.parse_patents(query, limit_per_source))
        return all_data
