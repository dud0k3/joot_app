# JOOT VPN — clean production v7

Telegram bot + Telegram Mini App + FastAPI + StealthSurf API.

Build version:

```text
joot-clean-production-2026-06-29-v7-joot8-ui-clean
```

## Что внутри v7

- Убрана кнопка `Открыть подписку` из сообщения бота.
- Mini App больше не показывает слово `stealthsurf` в карточке.
- StealthSurf custom subscription создаётся как JOOT bundle: 1 Auto config + 7 regular configs.
- Названия конфигов стали короткими: `JOOT Auto`, `JOOT VLESS`, `JOOT Trojan`, `JOOT Hysteria` и т.д.
- Если старая активная подписка содержит меньше 8 конфигов, бот пересоберёт её при `Подключить VPN` или `Обновить подписку`.
- Основная ссылка подписки остаётся обычной: `https://connect.stealthsurf.net/to/...`.

## Dockhost

Network disk:

```text
joot-data → /data
```

Database:

```env
DATABASE_URL=sqlite:////data/joot.db
```

Health checks:

```text
/health
/api/version
```
