#!/usr/bin/env bash
# Скачивает корневой сертификат НУЦ Минцифры в certs/russian_trusted_ca.pem.
#
# Он нужен для обращений к GigaChat: домены Сбера подписаны российским
# корневым центром сертификации, которого нет ни в системном хранилище,
# ни в пакете certifi. Без него запрос падает на проверке TLS.
#
# Сертификат публичный, лежит на портале госуслуг. Скачанный файл
# кладётся в репозиторий: иначе стенд и жюри получат ту же ошибку.
#
# Запуск:  bash scripts/install_ru_certs.sh
#
# Имена переменных латиницей намеренно: bash 3.2, который стоит в macOS
# по умолчанию, не понимает кириллицу в именах.

set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="$PROJECT_ROOT/certs"
CERT_FILE="$CERT_DIR/russian_trusted_ca.pem"

ROOT_URL="https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
SUB_URL="https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt"

mkdir -p "$CERT_DIR"
TMP_FILE="$CERT_DIR/.download.tmp"

echo "Скачиваю корневой сертификат НУЦ Минцифры..."
# -k здесь осознанно: сам сертификат нужен именно для того, чтобы проверять
# цепочку, и на этом хосте её пока проверить нечем. Скачанное ниже
# проверяется на осмысленность и дальше служит доверенным корнем только
# для доменов Сбера.
if ! curl -fsSL -k "$ROOT_URL" -o "$TMP_FILE"; then
  rm -f "$TMP_FILE"
  echo "Не удалось скачать $ROOT_URL" >&2
  echo "Откройте https://www.gosuslugi.ru/crt, скачайте корневой сертификат" >&2
  echo "и сохраните его как certs/russian_trusted_ca.pem" >&2
  exit 1
fi

echo "Скачиваю выпускающий сертификат..."
printf '\n' >> "$TMP_FILE"
curl -fsSL -k "$SUB_URL" >> "$TMP_FILE" || \
  echo "Выпускающий сертификат не скачался, продолжаем с одним корневым."

if ! grep -q "BEGIN CERTIFICATE" "$TMP_FILE"; then
  rm -f "$TMP_FILE"
  echo "Скачался не сертификат. Проверьте доступность $ROOT_URL" >&2
  exit 1
fi

mv "$TMP_FILE" "$CERT_FILE"
COUNT="$(grep -c "BEGIN CERTIFICATE" "$CERT_FILE")"
echo "Готово: $CERT_FILE (сертификатов в файле: $COUNT)"
echo
echo "Проверка соединения со Сбером:"
cd "$PROJECT_ROOT" && python -m src.texts.certs || true
echo
echo "Добавьте файл в репозиторий, иначе на стенде GigaChat не заработает:"
echo "  git add certs/russian_trusted_ca.pem"
