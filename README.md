<p align="center">
  <img src="./assets/logo.svg" alt="unitedgram" width="640">
</p>

<p align="center">
  <b>Ponte bidirecional em tempo real entre <code>UNIT3D</code> e <code>Telegram</code>.</b>
</p>

<p align="center">

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot_API-2CA5E0?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Socket.IO](https://img.shields.io/badge/Socket.IO-EIO_v3-010101?logo=socketdotio&logoColor=white)](https://socket.io/)

</p>

Ponte **bidirecional em tempo real** entre um chat de tracker **UNIT3D** e um grupo/tópico do **Telegram**. Você lê e responde o shoutbox do tracker direto do Telegram, sem abrir o navegador.

---

## ✨ O que ele faz

- 💬 **Mensagens do site → Telegram** em tempo real (via WebSocket)
- 📤 **Mensagens do Telegram → site** (com suporte a BBCode, imagens e replies)
- 🖼️ **Imagens nos dois sentidos** — site usa imgbb pra hospedar uploads do Telegram
- 🧵 **Threading de respostas** preservado entre os dois lados
- 🗑️ **Botão de deletar** nas suas próprias mensagens (apaga em ambos)
- 🔔 **Menções a você** no site viram marcações no Telegram
- 🚨 **Alerta automático** se a sessão/cookie do site expira
- 💓 **Heartbeat + health check** pra debugar remotamente
- 🔄 **Reconexão WS automática** com fallback HTTP quando cai

---

## 🛠️ Tecnologias

| Camada | Biblioteca | Pra quê |
|---|---|---|
| Bot Telegram | [`python-telegram-bot`](https://python-telegram-bot.org/) 22.x | API oficial |
| HTTP async | [`httpx`](https://www.python-httpx.org/) | Chamadas ao site |
| WebSocket | [`python-socketio`](https://python-socketio.readthedocs.io/) 4.x | Eventos em tempo real (EIO v3, Socket.IO 2.x) |
| Parsing HTML | [`beautifulsoup4`](https://www.crummy.com/software/BeautifulSoup/) + `lxml` | Limpeza de HTML do shoutbox |
| Config | [`python-dotenv`](https://github.com/theskumar/python-dotenv) | Carregar `.env` |
| Testes | [`pytest`](https://docs.pytest.org/) + `pytest-asyncio` | Unit + async tests |

---

## 📋 Pré-requisitos

- 🐍 **Python 3.11+**
- 🖥️ **Um computador que possa, de preferência, ficar ligado direto** (pra manter o chat funcionando)
- 🤖 **Token de bot do Telegram** ([@BotFather](https://t.me/BotFather))
- 🍪 **Conta ativa no tracker UNIT3D** (pra extrair cookies e CSRF)
- 🖼️ **(Opcional) API key da [imgbb](https://api.imgbb.com/)** — grátis, pra hospedar imagens enviadas do Telegram

---

## 🚀 Instalação

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
| `USER_ID` | Seu ID numérico no site |
| `CSRF_TOKEN` | Meta tag `<meta name="csrf-token">` ou cookie `XSRF-TOKEN` |
| `COOKIE` | Cookie completo da sua sessão logada (DevTools → Application → Cookies → copie o header `Cookie` inteiro) |

#### 💬 Telegram (obrigatórias)

| Var | Onde pegar |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Envie uma msg pro [@userinfobot](https://t.me/userinfobot) no grupo/chat; negativo pra grupos |
| `TELEGRAM_TOPIC_ID` | (Opcional) ID do tópico se for supergrupo com tópicos |

#### 👤 Identidade (opcionais mas recomendadas)

| Var | Pra quê |
|---|---|
| `MY_USERNAME` | Seu username no site (detecta suas mensagens) |
| `TELEGRAM_USER` | Seu handle no Telegram (sem `@`) — menções viram tag clicável |
| `MY_ALIASES` | Outros apelidos pelos quais te chamam no chat, separados por vírgula |
| `IMGBB_API_KEY` | Key grátis pra hospedar imagens do Telegram → site |

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
<summary><b>🕵️ Extrair <code>USER_ID</code> e <code>CSRF_TOKEN</code> do site</b></summary>

1. Abra o site **logado**
2. `F12` → aba **Console**
3. Cole e aperte **Enter**:

```js
(function() {
    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.content : "CSRF NÃO ENCONTRADO";

        let userID = "USER_ID NÃO ENCONTRADO";
        const chatbox = document.querySelector('#chatbody');
        if (chatbox) {
            const xData = chatbox.getAttribute('x-data') || '';
            const match = xData.match(/\\u0022id\\u0022:(\d+)/) || xData.match(/"id":(\d+)/);
            if (match && match[1]) userID = match[1];
        }

        if (userID === "USER_ID NÃO ENCONTRADO") {
            const wireElements = document.querySelectorAll('[wire\\:snapshot]');
            for (let el of wireElements) {
                try {
                    const snapshot = JSON.parse(el.getAttribute('wire:snapshot'));
                    if (snapshot?.data?.user?.[1]?.key) {
                        userID = snapshot.data.user[1].key;
                        break;
                    }
                } catch (e) {}
            }
        }

        console.log("%c COPIE OS DADOS ABAIXO:", "background:#222;color:#bada55;font-size:15px;padding:5px;border-radius:3px;");
        console.log("USER_ID: " + userID);
        console.log("CSRF_TOKEN: " + csrfToken);
    } catch (error) {
        console.error("Erro:", error);
    }
})();
```

Copie os valores que aparecerem no console.

> Se `USER_ID NÃO ENCONTRADO`, você não está numa página com o chatbox visível. Volte pra home do tracker e tente de novo.

</details>

<details>
<summary><b>🍪 Extrair o <code>COOKIE</code> completo da sessão</b></summary>

1. Ainda no `F12`, vá na aba **Network** (ou Rede)
2. Aperte **F5** pra recarregar a página
3. No filtro, digite `doc` (ou clique em **HTML**)
4. Clique no **primeiro item** da lista (geralmente tem o nome do site)
5. Lateral direita → aba **Headers** → role até **Request Headers**
6. Procure a linha **Cookie**
7. Copie **TUDO** que está depois de `Cookie:` (é uma linha longa com `laravel_session=...; XSRF-TOKEN=...; remember_web=...`)

Cola inteiro entre aspas no `.env`:

```env
COOKIE="remember_web_xxx=...; laravel_cookie_consent=1; XSRF-TOKEN=...; laravel_session=..."
```

⚠️ O cookie **pode expirar** depois de algumas semanas. Se isso acontecer, o bot te avisa no próprio Telegram com `🚨 Sessão expirada` — repita o processo e atualize o `.env`.

</details>

---

### 3. Teste local

```bash
./venv/bin/python -m pytest   # 71 testes, deve passar tudo
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

---

## 🎮 Comandos no Telegram

| Comando | Função |
|---|---|
| `/ping` | Responde `pong 🏓`. Teste de sanidade. |
| `/status` | Uptime, tamanho da queue, se WS tá conectado, contadores de cache. |

E mensagens comuns no chat Telegram viram mensagens no shoutbox do site. Responder uma mensagem (reply do Telegram) vira uma citação BBCode automática.

---

## 🔧 Customização

**15 variáveis opcionais** controlam timeouts, intervalos, limites de cache, backoff de reconexão, features. Tudo documentado no `.env.example`.

Destaques:

- `BACKFILL_COUNT=10` — msgs entregues no startup (0 = pular histórico)
- `MIRROR_DELETIONS=false` — se `true`, apagar no site também apaga no Telegram
- `SHOW_DELETE_BUTTON=true` — botão 🗑️ nas suas mensagens
- `TAG_ALIASES=true` — `@seunome` vira tag clicável

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
