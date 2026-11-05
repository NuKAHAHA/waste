# CI/CD: Docker + Jenkins (+ Minikube)

Assignment 5. Пайплайн для модуля Smart Waste Astana (5 агентов).

```
git push ─▶ Jenkins (pollSCM, раз в 2 мин)
            ├─ Checkout
            ├─ Unit tests     — 30 тестов в контейнере, отчёт JUnit
            ├─ Build image    — smart-waste-astana:<build>-<sha>, :latest
            ├─ Smoke test     — не root, demo печатает OK:, analyze на CSV, артефакты
            ├─ Push to Docker Hub   (по желанию, PUSH_IMAGE)
            ├─ Deploy to staging    — контейнер на http://localhost:8088
            └─ Deploy to Kubernetes (по желанию, DEPLOY_K8S, Minikube)
```

| Файл | Назначение |
|---|---|
| `Dockerfile` | Многоступенчатая сборка: `test` (тесты + JUnit) и `runtime` (не root) |
| `.dockerignore` | Не пускает в образ `.git`, `.env`, результаты, документы |
| `Jenkinsfile` | Декларативный пайплайн |
| `tools/junit_runner.py` | Запуск unittest с отчётом JUnit XML без сторонних библиотек |
| `tools/serve.py` | Запуск агентов и раздача `dashboard.html` по HTTP, `/healthz` |
| `ci/jenkins/` | Jenkins в Docker: плагины, Docker CLI, kubectl, Configuration as Code |
| `k8s/` | Namespace, Deployment (2 реплики, пробы, лимиты), Service NodePort 30080 |

## 1. Проверить Docker-образ вручную

Нужен Docker Desktop (Windows/macOS) или Docker Engine (Linux).

```bash
cd research/smart-waste-astana
docker build --target test -t smart-waste-astana:test .
docker run --rm smart-waste-astana:test          # 30 тестов, OK
docker build -t smart-waste-astana .
docker run --rm smart-waste-astana                # OK: 24 bins, 8 selected, 2 trips
docker run --rm -p 8088:8080 --entrypoint python smart-waste-astana tools/serve.py
# открыть http://localhost:8088
```

## 2. Поднять Jenkins

```bash
cd research/smart-waste-astana/ci/jenkins
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
# в .env задать JENKINS_ADMIN_PASSWORD
docker compose up -d --build
docker compose logs -f jenkins   # дождаться "Jenkins is fully up and running"
```

Открыть http://localhost:8080 и войти как `admin`. Мастер настройки не появится:
пользователь, плагины и задача `smart-waste-astana` создаются из `casc.yaml`.

## 3. Запустить пайплайн

1. Открыть задачу **smart-waste-astana** → **Build Now**.
   Первый запуск подхватывает параметры из Jenkinsfile; дальше появится **Build with Parameters**.
2. Сделать коммит в `main` и отправить его (`git push`). Через 1–2 минуты Jenkins сам запустит сборку.
   Это и есть «тесты на каждый коммит».
3. Staging после успешной сборки: http://localhost:8088

## 4. Скриншоты для сдачи

1. Страница задачи со **Stage View**: все стадии зелёные.
2. **Pipeline Graph** (`Pipeline Overview` в меню сборки).
3. **Test Result**: 30 тестов, 0 ошибок.
4. **Console Output**: строки `Ran 30 tests ... OK` и `OK: 24 bins, 8 selected, 2 trips`.
5. **Build Artifacts**: `dashboard.html`, `report.json`, `priorities.csv`.
6. История сборок, где видно «Started by an SCM change».
7. Открытый http://localhost:8088 (дашборд из staging-контейнера).
8. `docker image ls smart-waste-astana` в терминале.
9. По желанию: Docker Hub со списком тегов, `kubectl -n smart-waste get pods,svc`.

## 5. Бонус: Docker Hub и Minikube

**Docker Hub.** Создать access token (Account Settings → Personal access tokens),
записать `DOCKERHUB_USER` и `DOCKERHUB_TOKEN` в `ci/jenkins/.env`,
выполнить `docker compose up -d` и запустить сборку с `PUSH_IMAGE=true`.

**Minikube** (драйвер docker):

```bash
minikube start --driver=docker
docker network connect minikube jenkins        # Jenkins увидит API кластера
minikube kubectl -- config view --flatten --minify > kubeconfig-jenkins.yaml
```

В `kubeconfig-jenkins.yaml` заменить адрес `server:` на `https://minikube:8443`
(на Windows/macOS там будет `https://127.0.0.1:<порт>`).
В Jenkins: **Manage Jenkins → Credentials → Global → Add**, тип *Secret file*, ID `kubeconfig`,
загрузить файл. Потом удалить локальную копию: в ней ключи от кластера.

Запустить сборку с `PUSH_IMAGE=true` и `DEPLOY_K8S=true`. Проверить:

```bash
kubectl -n smart-waste get pods,svc
minikube service smart-waste -n smart-waste
```

## Ограничения

- Jenkins запущен от root и с доступом к Docker-сокету хоста. Для учебного стенда на своём
  компьютере это нормально, выставлять такой Jenkins в интернет нельзя.
- GitHub не может отправить webhook на `localhost`, поэтому используется опрос репозитория
  раз в 2 минуты. Несколько коммитов за это время попадут в одну сборку.
  Для мгновенного запуска нужен публичный адрес (например, ngrok) и webhook GitHub.
- GitHub Actions (`.github/workflows/smart-waste-ci.yml`) продолжает работать параллельно.
