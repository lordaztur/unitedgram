# 💬 Tutorial: Bot do Telegram

Guia passo a passo pra criar o bot do Telegram, configurar no grupo/tópico, e popular as variáveis de ambiente.

> Pré-requisito: já ter clonado o projeto e exportado o `cookies/cookies.txt` do tracker. Veja o [README](../README.md#instalação) pra esses passos gerais.

---

## 1. Criar o bot

1. No Telegram, abra [@BotFather](https://t.me/BotFather) e mande `/newbot`.
2. Dê um nome (ex: *MeuBridge*).
3. Crie um username terminado em `bot` (ex: *meubridge_bot*).
4. O BotFather devolve um token longo — copie pra `TELEGRAM_BOT_TOKEN` no seu `.env`.

---

## 2. Liberar leitura de grupo

Bots **não leem mensagens de grupo por padrão**. Pra liberar:

1. No [@BotFather](https://t.me/BotFather), mande `/setprivacy`.
2. Selecione seu bot.
3. Escolha **DISABLE**.

Depois, adicione o bot ao grupo do Telegram como **administrador** — senão ele não consegue apagar mensagens (em sucesso de envio) nem postar em tópicos de supergrupo.

---

## 3. Pegar o `TELEGRAM_CHAT_ID`

Forma mais simples:

1. Adicione [@userinfobot](https://t.me/userinfobot) ao seu grupo.
2. O bot responde com o ID do grupo (negativo, formato `-100xxxxxxxxxx`).
3. Pode remover o `@userinfobot` depois.

---

## 4. (Opcional) `TELEGRAM_TOPIC_ID`

Se o grupo for um supergrupo com tópicos:

1. Entre no tópico onde o bot deve postar.
2. Copie o link de qualquer mensagem do tópico (ex: `t.me/c/123456789/42/100`).
3. O número do meio (`42` nesse exemplo) é o `TOPIC_ID`.

Se você não usa tópicos, deixe a variável comentada no `.env`.

---

## 5. Variáveis no `.env`

| Var | Obrigatória? | Valor |
|---|---|---|
| `ENABLE_TELEGRAM` | Sim (pra ativar) | `true` |
| `TELEGRAM_BOT_TOKEN` | Sim | Token do BotFather |
| `TELEGRAM_CHAT_ID` | Sim | ID numérico do grupo (negativo) |
| `TELEGRAM_TOPIC_ID` | Opcional | ID do tópico (só supergrupo com tópicos) |
| `TELEGRAM_USER` | Recomendada | Seu handle no TG (sem `@`). Quando aliases seus são citados no chat do site, vira tag clicável `[@SeuHandle]` na mensagem espelhada |

As variáveis comuns (site, identidade, imgbb) estão na seção `.env` do [README principal](../README.md#2-configure-o-env).

---

## 6. Comandos disponíveis

| Comando | Função |
|---|---|
| `/ping` | Responde `pong 🏓`. Teste de sanidade. |
| `/status` | Uptime, status do WebSocket, tamanho da queue, contadores de cache. |
| `/online` | Lista quem está no chat do site agora. Avisa se o WebSocket caiu. |

---

## 7. Comportamento

**Telegram → site**:
- Digite no chat onde o bot está. Em **sucesso**, sua mensagem é apagada do Telegram (vai aparecer pelo bot, formatada).
- Em **falha**, o bot reage com 👎 na sua mensagem original.
- Use **Responder** do Telegram em uma mensagem do bot pra criar uma citação BBCode automática no site.
- **Imagens** (foto solo ou álbum): mande normalmente. Com `IMGBB_API_KEY` configurada, o bot sobe no imgbb (auto-delete em 12h por padrão) e posta `[img]url[/img]` no site.

**Site → Telegram**:
- Cada mensagem do chat vira uma mensagem no Telegram, formatada com nome do remetente em **negrito** e o texto.
- **Avatar como preview**: mensagens texto-puro mostram um card pequeno embaixo com o avatar do usuário do site (cache persistente, revalidação por hash). Requer `IMGBB_API_KEY` pra avatares custom; placeholder default funciona sem.
- **Botão 🗑️ Deletar**: suas próprias mensagens (detectadas via `MY_USERNAME`/`MY_ALIASES`) ganham um botão inline — apaga em ambos os lados quando clicado.
- **Quotes/citações** do site são renderizadas como `<blockquote>` no Telegram.
- **Emojis joypixels** do site (PNGs inline) são convertidos pra unicode nativo no Telegram.
- **GIFs**: enviados como `send_animation` (animados, não estáticos).

---

## 8. Troubleshooting

- **Bot não responde a `/ping`**: verifique se está como admin do grupo, e se `/setprivacy` foi setado pra DISABLE no BotFather.
- **Mensagens do site não aparecem**: cheque `bot_bridge.log` por erros de WS ou cookie. Sessão pode ter expirado — reexporte `cookies/cookies.txt`.
- **Avatares não aparecem**: cheque se `IMGBB_API_KEY` está setada. Sem ela, mostra só o nome do remetente.
- **❌ no upload de imagem**: o imgbb pode estar fora ou rate-limitando. O bot tenta reenvio com backoff de 429.
