<p align="center">
  <img src="./assets/logo.svg" alt="unitedgram" width="640">
</p>

<p align="center">
  <b>Ponte bidirecional em tempo real entre <code>UNIT3D</code>, <code>Telegram</code> e <code>Discord</code>.</b>
</p>

<p align="center">

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot_API-2CA5E0?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Discord](https://img.shields.io/badge/Discord-Bot_API-2CA5E0?logo=discord&logoColor=white)](https://discord.com/developers/)
[![Socket.IO](https://img.shields.io/badge/Socket.IO-EIO_v3-010101?logo=socketdotio&logoColor=white)](https://socket.io/)

</p>

Ponte **bidirecional em tempo real** entre um chat de tracker **UNIT3D** e plataformas de mensagens (**Telegram** e/ou **Discord**). Você lê e responde o shoutbox do tracker direto dos seus apps favoritos, de forma totalmente flexível e simultânea.

---

## ✨ O que ele faz

- 💬 **Mensagens do site → Bots** em tempo real (via WebSocket)
- 📤 **Mensagens dos Bots → site** (suporte a BBCode, imagens e replies em ambas as plataformas)
- 🖼️ **Imagens bidirecionais** — suporte a upload via ImgBB para anexos vindos do Telegram/Discord
- 👤 **Avatares Premium** — No Telegram (via ImgBB) e Discord (Embeds nativos com suporte a **GIFs animados**)
- 👥 **`/online`** (Telegram) ou `!online` (Discord) mostra quem está no chat agora
- 🧵 **Threading de respostas** preservado entre todas as pontas
- 🗑️ **Botão de deletar** (Telegram) — apaga a mensagem em todos os lugares
- 🔌 **Arquitetura Flexível** — Rode apenas com Discord, apenas com Telegram ou ambos ao mesmo tempo
- 🔔 **Menções a você** no site viram marcações no Telegram
- 🚨 **Alerta automático** se a sessão/cookie do site expira
- 💓 **Heartbeat + health check** pra debugar remotamente
- 🔄 **Reconexão WS automática** com fallback HTTP quando cai

---

## 🛠️ Tecnologias

| Camada | Biblioteca | Pra quê |
|---|---|---|
| Bot Discord | [`discord.py`](https://discordpy.readthedocs.io/) 2.x | API oficial do Discord |
| Imagens | [`Pillow`](https://python-pillow.org/) | Processamento e resize de avatares (incluindo GIFs) |
| Config | [`python-dotenv`](https://github.com/theskumar/python-dotenv) | Carregar `.env` |
| Testes | [`pytest`](https://docs.pytest.org/) + `pytest-asyncio` | Unit + async tests |

---

## 📋 Pré-requisitos

- � **Docker instalado** — necessário para rodar via container
- 🐍 **Python 3.11+**
- 🖥️ **Um computador que possa, de preferência, ficar ligado direto** (pra manter o chat funcionando)
- 🤖 **Token de bot do Telegram** (Opcional) ou **Bot do Discord** (Opcional)
- 🖼️ **API key da [imgbb](https://api.imgbb.com/)** — Recomendada para avatares e envio de imagens

---

## 🚀 Instalação

> Se você for usar Docker, execute apenas os passos 1 e 2. Os passos 3, 4 e 5 são desnecessários para uso em Docker.

### 1. Clone e crie o venv

```bash
git clone <url-do-repo> unitedgram
cd unitedgram
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure o `.env`

```bash
cp .env.example .env
chmod 600 .env                  # só você lê/escreve (tem secrets dentro)
```

Edite `.env` preenchendo:

#### 🌐 Site (todas obrigatórias)

| Var | Onde pegar |
|---|---|
| `BASE_URL` | URL do tracker sem barra final (ex: `https://tracker.com`) |
| `WS_HOST` | Mesmo host do `BASE_URL`, sem porta (a porta vem do `WS_PORT`, default `8443`) |
| `CHATROOM_ID` | ID da sala (descubra em `/api/chat/rooms` logado) |

> 🍪 **Cookies não vão no `.env`**. Salve um arquivo Netscape `cookies.txt` em `cookies/cookies.txt` — o bot lê de lá, refresca a sessão sozinho a cada 4h e descobre `USER_ID` e `CSRF_TOKEN` dinamicamente. Detalhes no passo abaixo.

#### 💬 Telegram (Opcional)
| Var | Onde pegar |
|---|---|
| `ENABLE_TELEGRAM` | `true` ou `false` |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | ID do grupo ou chat |
| `TELEGRAM_TOPIC_ID` | (Opcional) ID do tópico |

#### 🎮 Discord (Opcional)
| Var | Onde pegar |
|---|---|
| `ENABLE_DISCORD` | `true` ou `false` |
| `DISCORD_BOT_TOKEN` | [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_CHANNEL_ID` | ID do canal de texto (botão direito no canal → Copiar ID) |

#### 👤 Identidade (opcionais mas recomendadas)

| Var | Pra quê |
|---|---|
| `MY_USERNAME` | Seu username no site (detecta suas mensagens) |
| `TELEGRAM_USER` | Seu handle no Telegram (sem `@`) — menções viram tag clicável |
| `DISCORD_USER_ID` | Seu ID numérico no Discord (para receber notificações/menções) |
| `MY_ALIASES` | Outros apelidos pelos quais te chamam no chat, separados por vírgula |
| `IMGBB_API_KEY` | Key grátis pra hospedar imagens do Telegram → site (imagens de mensagem se auto-deletam após **12h** no imgbb por padrão — configurável via `IMGBB_MSG_EXPIRATION_SECONDS`; avatares ficam permanentes) |

> 💡 Todas as outras variáveis do `.env.example` são **tuning opcional** com defaults sensatos. Veja o arquivo pra detalhes de cada uma.

---

#### 🧭 Como pegar os valores na prática

<details>
<summary><b>🤖 Criar o bot no Telegram e liberar leitura de grupo</b></summary>

1. Abra [@BotFather](https://t.me/BotFather), mande `/newbot`
2. Dê um nome (ex: *MeuBridge*)
3. Crie um username terminado em `bot` (ex: *meubridge_bot*)
4. Copie o token que aparece → `TELEGRAM_BOT_TOKEN`

⚠️ **Importante:** bots **não leem mensagens de grupo por padrão**. Libere:

- No [@BotFather](https://t.me/BotFather) mande `/setprivacy`
- Selecione seu bot → escolha **DISABLE**

E no grupo do Telegram, **adicione o bot como admin** (senão ele não consegue apagar mensagens dele próprio, enviar em tópicos, etc.).

</details>

<details>
<summary><b>🍪 Exportar o <code>cookies.txt</code> do navegador</b></summary>

Use uma extensão que exporta cookies no **formato Netscape** (o que o bot espera):

- Chrome / Edge: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
- Firefox: [cookies.txt](https://addons.mozilla.org/firefox/addon/cookies-txt/)

Passos:

1. Faça login no tracker normalmente.
2. Abra a extensão (ícone na barra) com a aba do tracker ativa.
3. **Exporte** os cookies daquele domínio (geralmente um botão "Export" ou "Download").
4. Salve o arquivo como `cookies.txt` dentro da pasta `cookies/` do projeto:

```
unitedgram/
└── cookies/
    └── cookies.txt
```

`USER_ID` e `CSRF_TOKEN` **não precisam** ser configurados — o bot os extrai automaticamente da home do site no primeiro request e refresca a cada `COOKIE_PROBE_INTERVAL` segundos (default 4h). Os cookies são também re-salvos no `.txt` a cada refresh, então a sessão se renova sozinha enquanto você mantiver o `remember_web` válido.

⚠️ Se a sessão expirar (logout no site, troca de IP, etc.), o bot te avisa no Telegram com `🚨 Sessão expirada`. Aí é só repetir o export e reiniciar.

</details>

---

### 3. Teste local

```bash
./venv/bin/python -m pytest   # 87 testes, deve passar tudo
./venv/bin/python main.py     # roda o bot em foreground (Ctrl+C pra parar)
```

Se vir no log:

```
📥 Backfill: entregando últimas 10 msg(s)
🤖 Bot Rodando (modo WebSocket)...
🔌 WS conectado
✅ Presence subscribed
💬 Nova msg via WS id=...
```

**Tá funcionando.** ✅

### 4. Rodar como service no Linux

Crie `/etc/systemd/system/unitedgram.service`:

```ini
[Unit]
Description=unitedgram (Telegram chat bridge)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=seu-usuario
WorkingDirectory=/caminho/para/unitedgram
ExecStart=/caminho/para/unitedgram/venv/bin/python /caminho/para/unitedgram/main.py
Restart=always
RestartSec=3
Environment=PYTHONUTF8=1
Environment=LC_ALL=C.UTF-8
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Então:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now unitedgram.service
sudo systemctl status unitedgram.service
```

Logs:
```bash
tail -f /caminho/para/unitedgram/bot_bridge.log       # log do bot
journalctl -u unitedgram.service -f                   # via journald
```

### 5. Rodar em macOS / Windows

O código Python é 100% portátil — roda direto com `python main.py` em qualquer OS que tenha Python 3.11+. Só muda o jeito de deixar rodando em segundo plano.

<details>
<summary><b>🍎 macOS — <code>launchd</code> (LaunchAgent)</b></summary>

Crie `~/Library/LaunchAgents/com.unitedgram.bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.unitedgram.bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>/caminho/para/unitedgram/venv/bin/python</string>
        <string>/caminho/para/unitedgram/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/caminho/para/unitedgram</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUTF8</key>
        <string>1</string>
        <key>LC_ALL</key>
        <string>en_US.UTF-8</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/caminho/para/unitedgram/bot_bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/caminho/para/unitedgram/bot_bridge.log</string>
</dict>
</plist>
```

Carregue o agent:

```bash
launchctl load ~/Library/LaunchAgents/com.unitedgram.bot.plist
launchctl start com.unitedgram.bot

# status
launchctl list | grep unitedgram

# parar / descarregar
launchctl stop com.unitedgram.bot
launchctl unload ~/Library/LaunchAgents/com.unitedgram.bot.plist
```

Logs: `tail -f /caminho/para/unitedgram/bot_bridge.log`

</details>

<details>
<summary><b>🪟 Windows — Task Scheduler (simples)</b></summary>

O jeito mais rápido, sem instalar nada:

1. Abra o **Agendador de Tarefas** (`taskschd.msc`)
2. **Criar Tarefa** (não "Tarefa Básica")
3. Aba **Geral**:
   - Nome: `unitedgram`
   - ☑ Executar estando o usuário conectado ou não
   - ☑ Executar com privilégios mais altos
4. Aba **Disparadores** → **Novo**:
   - Iniciar a tarefa: **Ao inicializar o sistema**
5. Aba **Ações** → **Nova**:
   - Ação: **Iniciar um programa**
   - Programa/script: `C:\caminho\para\unitedgram\venv\Scripts\python.exe`
   - Adicionar argumentos: `main.py`
   - Iniciar em: `C:\caminho\para\unitedgram`
6. Aba **Configurações**:
   - ☑ Se a tarefa falhar, reiniciar a cada: **1 minuto**
   - Tentar reiniciar até: **999** vezes
   - ☐ Parar a tarefa se for executada mais de (desmarque)

Testar: clique direito na tarefa → **Executar**. O log sai em `bot_bridge.log` dentro da pasta do projeto.

</details>

<details>
<summary><b>🪟 Windows — <a href="https://nssm.cc/">NSSM</a> (rodar como Windows Service)</b></summary>

Se quiser um serviço de verdade (aparece em `services.msc`, start automático, recovery nativo):

```powershell
# instale o NSSM (via choco, scoop, ou baixe em nssm.cc)
choco install nssm

# registre o serviço
nssm install unitedgram "C:\caminho\para\unitedgram\venv\Scripts\python.exe" "main.py"
nssm set unitedgram AppDirectory "C:\caminho\para\unitedgram"
nssm set unitedgram AppEnvironmentExtra "PYTHONUTF8=1"
nssm set unitedgram AppStdout "C:\caminho\para\unitedgram\bot_bridge.log"
nssm set unitedgram AppStderr "C:\caminho\para\unitedgram\bot_bridge.log"
nssm set unitedgram Start SERVICE_AUTO_START
nssm set unitedgram AppExit Default Restart
nssm set unitedgram AppRestartDelay 3000

# controle
nssm start unitedgram
nssm status unitedgram
nssm stop unitedgram
nssm remove unitedgram confirm     # desinstalar
```

</details>

> 💡 **Nota sobre permissões do `.env`**: o `chmod 600` do passo 2 é específico de Unix. No Windows, a proteção já vem do NTFS herdando a permissão do seu usuário — se quiser travar explicitamente, use `icacls .env /inheritance:r /grant:r "%USERNAME%:F"`.



## 🐳 Usando com Docker

### Rodar o container usando docker compose:

O repositório já inclui um `Dockerfile` e um `docker-compose.yml`.

O `docker-compose.yml` monta dois volumes pra preservar estado entre rebuilds:

- `./avatar_cache.json` → cache de avatares (precisa existir como arquivo)
- `./cookies/` → diretório onde o bot lê/atualiza `cookies.txt` da sessão

**Antes do primeiro `up`**, prepare os dois (senão o Docker pode criar `avatar_cache.json` como diretório, e o bot fica sem sessão):

```bash
echo '{}' > avatar_cache.json
mkdir -p cookies
# Exporte cookies.txt do navegador (veja Passo 2) e salve em cookies/cookies.txt
docker compose up -d
```

#### Com Signal habilitado

O sidecar `signal-cli-rest-api` está num **profile opcional** (`signal`), então só sobe se você pedir. Pra rodar com Signal:

```bash
docker compose --profile signal up -d
```

Dentro do container, o unitedgram acessa o sidecar pelo hostname `signal-cli` (DNS do Compose), então use no `.env`:

```env
SIGNAL_API_URL="http://signal-cli:8080"
```

(Quando rodando o bot fora do Docker e o sidecar dentro, use `http://localhost:8080`.)

**Vinculação do dispositivo Signal (one-time)**: após o sidecar subir, abra `http://localhost:8080/v1/qrcodelink?device_name=unitedgram` no navegador e escaneie o QR no Signal mobile (Settings → Linked devices). Os dados de identidade ficam persistidos em `./signal-cli-data`.

Para ver os logs em tempo real:

```bash
docker compose logs -f
```
Para parar o serviço:

```bash
docker compose down
```
---

## 🎮 Comandos no Telegram

| Comando | Função |
|---|---|
| `/ping` | Responde `pong 🏓`. Teste de sanidade. |
| `/status` | Uptime, status do WebSocket e contadores. |
| `/online` | Lista quem está no chat do site agora. |

## 🎮 Comandos no Discord
| Comando | Função |
|---|---|
| `!ping` | Responde `pong 🏓`. |
| `!online` | Lista quem está no chat do site agora. |

E mensagens comuns no chat Telegram viram mensagens no shoutbox do site. Responder uma mensagem (reply do Telegram) vira uma citação BBCode automática.

---

## 🔧 Customização

**15 variáveis opcionais** controlam timeouts, intervalos, limites de cache, backoff de reconexão, features. Tudo documentado no `.env.example`.

Destaques:

- `BACKFILL_COUNT=10` — msgs entregues no startup (0 = pular histórico)
- `MIRROR_DELETIONS=false` — se `true`, apagar no site também apaga no Telegram
- `SHOW_DELETE_BUTTON=true` — botão 🗑️ nas suas mensagens
- `TAG_ALIASES=true` — `@seunome` vira tag clicável
- `SHOW_USER_AVATARS=true` — preview do avatar do remetente no Telegram (requer `IMGBB_API_KEY` pra avatares custom)
- `AVATAR_REVALIDATE_SECONDS=1800` — TTL do cache de avatar; pós-expiração, baixa de novo e só re-sobe se mudou
- `IMGBB_MSG_EXPIRATION_SECONDS=43200` — tempo que imagens de mensagem ficam no imgbb antes do auto-delete (default 12h). **`0` = nunca deletar** (permanente). Range válido do imgbb: 60–15552000s. Avatares NÃO são afetados.

**Sobre o imgbb:** quando você manda uma foto/álbum do Telegram pro site, o bot sobe a imagem no imgbb com **expiração de 12 horas** por padrão (auto-delete pelo lado do imgbb). É tempo suficiente pra todo mundo ver no chat, mas não fica eternamente hospedado no seu account. Ajuste via `IMGBB_MSG_EXPIRATION_SECONDS` no `.env` — use `0` se quiser que fiquem permanentes. Avatares **não** usam expiração — ficam sempre permanentes (revalidação por hash cuida da atualização).

---

## 🧪 Testes

```bash
./venv/bin/python -m pytest          # tudo
./venv/bin/python -m pytest -v       # verboso
./venv/bin/python -m pytest tests/test_bridge_parsers.py   # só um arquivo
```

Cobre: parsing de HTML, formatação de mensagens Telegram, extração de replies, validação de env, auth flow, dedup/backfill, HTTP client mockado.

---

## 🏗️ Arquitetura

```
┌────────────┐   WebSocket (wss://host:8443)   ┌──────────────┐
│   site     │ ◀── eventos em tempo real ───▶│              │
│  UNIT3D    │                                 │              │
│            │       HTTP (site REST API)      │              │
│            │ ◀───── fallback + send ──────▶│  unitedgram  │
└────────────┘                                 │    (bot)     │
                                               │              │
                                               │              │
                                               │              │
┌────────────┐          Bot API (polling)      │              │
│  Telegram  │ ◀──────── send/receive ──────▶│              │
│  (chat)    │                                 │              │
└────────────┘                                 └──────────────┘
```

**6 módulos:**
- `main.py` — entrypoint, wiring de tasks
- `config.py` — setup de logging, carrega `.env`, defaults dos knobs
- `bridge.py` — client HTTP do site + parsers BBCode/HTML
- `site_listener.py` — WS client, worker de entrega, health checks
- `telegram_handlers.py` — comandos e forward de Telegram → site
- `formatting.py` — renderização de mensagens pro Telegram

---

## 📝 Licença

[MIT](./LICENSE) — use, modifique, distribua à vontade, só mantenha o aviso de copyright.
