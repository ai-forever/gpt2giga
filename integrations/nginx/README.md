# Развёртывание gpt2giga за nginx (Ubuntu)

Краткая инструкция по установке прокси gpt2giga на сервер Ubuntu с nginx, Docker и TLS-сертификатом (Let's Encrypt).

---

## 1. Подготовка сервера

Клонируйте репозиторий и установите базовые пакеты:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
```

---

## 2. Файрвол (UFW)

Откройте порты для SSH, HTTP и HTTPS и включите файрвол:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

---

## 3. Nginx

Установите nginx и включите его автозапуск:

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable --now nginx
```

---

## 4. Docker

Пакеты Docker в стандартных репозиториях Ubuntu часто отсутствуют. Добавьте официальный репозиторий Docker:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg software-properties-common

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

docker --version  && docker compose version
```

---

## 5. Certbot (сертификаты Let's Encrypt)

### Вариант A: через Snap (рекомендуется)

```bash
sudo apt update
sudo apt install -y snapd
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
certbot --version
```

---

## 6. Получение TLS-сертификата

Сертификат выдаётся на внешний IP сервера (для доступа по IP, без домена).

Узнайте внешний IP и остановите nginx (порт 80 нужен certbot):

```bash
PUBLIC_IP="$(curl -s https://api.ipify.org)"
echo "$PUBLIC_IP"
sudo systemctl stop nginx
```

Получите сертификат (подставьте свой email вместо `you@example.com`):

```bash
sudo certbot certonly --standalone \
  --ip-address "$PUBLIC_IP" \
  --preferred-profile shortlived \
  --cert-name gpt2giga-ip \
  -m you@example.com --agree-tos
```

Проверьте, что файлы появились:

```bash
sudo ls -la /etc/letsencrypt/live/gpt2giga-ip/
```

---

## 7. Настройка nginx

Скопируйте конфиг из репозитория в sites-available и создайте симлинк:

```bash
# Выполняйте из корня репозитория gpt2giga
sudo cp integrations/nginx/gpt2giga.conf /etc/nginx/sites-available/gpt2giga
sudo ln -sf /etc/nginx/sites-available/gpt2giga /etc/nginx/sites-enabled/gpt2giga
sudo rm -f /etc/nginx/sites-enabled/default
```

Проверьте конфиг и перезагрузите nginx:

```bash
sudo systemctl enable --now nginx
sudo nginx -t && sudo systemctl reload nginx
```

При необходимости отредактируйте конфиг (пути к сертификатам уже указаны под `gpt2giga-ip`):

```bash
sudo vim /etc/nginx/sites-available/gpt2giga
```

---

## 8. Запуск gpt2giga (Docker)

В корне репозитория создайте `.env` из примера и заполните переменные (GigaChat, режим PROD, API-ключ и т.д.):

```bash
cp .env.example .env
vim .env
# Отредактируйте .env (GIGACHAT_*, GPT2GIGA_*)
```

Запустите стек с профилем PROD (включая observability при необходимости):

```bash
docker compose -f docker-compose-observability.yaml --profile PROD up -d
```

---

## 9. Проверка

Откройте в браузере (подставьте свой `PUBLIC_IP`):

`echo "$PUBLIC_IP"`
- **Прокси (gpt2giga):** `https://PUBLIC_IP/`
- **Observability (mitmweb):** `https://PUBLIC_IP/observability/`

Проверка здоровья API:

```bash
curl -k https://PUBLIC_IP/health
```

Ожидаемый ответ: `{"status":"ok","mode":"PROD"}`.

---

## Полезные замечания

- Конфиг nginx (`gpt2giga.conf`) рассчитан на сертификат `gpt2giga-ip` и проксирование на `127.0.0.1:8090` (gpt2giga) и `127.0.0.1:8081` (observability).
- Шаблон переменных окружения: `integrations/nginx/.env.example` (или корневой `.env.example`).
- Для production обязательно задайте `GPT2GIGA_MODE=PROD`, включите API-key и ограничьте CORS — см. комментарии в `.env.example`.
