# 🎮 Tutorial: Bot do Discord

Guia passo a passo pra criar o bot do Discord, configurar no servidor/canal, e popular as variáveis de ambiente.

> Pré-requisito: já ter clonado o projeto e exportado o `cookies/cookies.txt` do tracker. Veja o [README](../README.md#instalação) pra esses passos gerais.

---

## 1. Criar a aplicação e o bot

1. Acesse o [Discord Developer Portal](https://discord.com/developers/applications).
2. Clique em **New Application** e dê um nome (ex: `Unitedgram`).
3. Na barra lateral, vá em **Bot**.
4. Em **Token**, clique **Reset Token** → confirma → copia o token longo. Esse é o `DISCORD_BOT_TOKEN`.

> ⚠️ O token só aparece uma vez. Se perder, precisa resetar de novo.

---

## 2. Habilitar Message Content Intent

O bot precisa ler o conteúdo das mensagens (não só metadados). Ainda na página **Bot**:

1. Role até **Privileged Gateway Intents**.
2. Ative **Message Content Intent**.
3. Salve as alterações.

Sem isso, o bot conecta mas todas as mensagens chegam vazias (`message.content == ""`).

---

## 3. Gerar URL de convite e adicionar ao servidor

Em **OAuth2** → **URL Generator** (ou **OAuth2 URL Generator** dependendo da versão da interface):

1. **Scopes**: marque **`bot`**.
2. **Bot Permissions**: marque pelo menos:
   - **Send Messages**
   - **Read Message History**
   - **Manage Messages** (necessária pra apagar mensagens em sucesso de envio)
   - **Attach Files** (avatares nos embeds)
   - **Add Reactions** (👎 em falha, 🗑️ pra delete-mirror)
   - **Embed Links**
3. Copie a URL gerada embaixo da página, abra no navegador, escolha o servidor → **Autorizar**.

---

## 4. Pegar o `DISCORD_CHANNEL_ID`

1. No Discord (app ou web), vá em **User Settings → Advanced** e ative o **Modo Desenvolvedor**.
2. Volte ao servidor, clique com botão direito no canal de texto onde o bot deve postar → **Copy Channel ID**.
3. Esse número (snowflake longo) é o `DISCORD_CHANNEL_ID`.

---

## 5. (Opcional) `DISCORD_USER_ID`

Pra que menções aos seus aliases no chat do site virem ping pra você no Discord:

1. Com Developer Mode ligado, clique com botão direito no seu perfil → **Copy User ID**.
2. Cole em `DISCORD_USER_ID` no `.env`.

Quando alguém te citar pelo username no UNIT3D, o bot transforma em `<@SEU_ID>` no Discord — o que vira menção clicável e te notifica.

---

## 6. Variáveis no `.env`

| Var | Obrigatória? | Valor |
|---|---|---|
| `ENABLE_DISCORD` | Sim (pra ativar) | `true` |
| `DISCORD_BOT_TOKEN` | Sim | Token do Developer Portal |
| `DISCORD_CHANNEL_ID` | Sim | ID do canal de texto |
| `DISCORD_USER_ID` | Opcional | Seu ID no Discord pra receber menções |

As variáveis comuns (site, identidade, imgbb) estão na seção `.env` do [README principal](../README.md#2-configure-o-env).

---

## 7. Comandos disponíveis

| Comando | Função |
|---|---|
| `!ping` | Responde `pong 🏓`. Teste de sanidade. |
| `!online` | Lista quem está no chat do site agora. |

---

## 8. Comportamento

**Discord → site**:
- Digite no canal configurado. Em **sucesso**, o bot apaga sua mensagem (ela vai aparecer pelo bot, formatada).
- Em **falha**, o bot reage com 👎 na sua mensagem original.
- Use **Responder** do Discord em uma mensagem do bot pra criar uma citação BBCode automática no site.
- **Imagens** (anexos): suportadas as extensões `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`. Com `IMGBB_API_KEY` configurada, o bot sobe no imgbb (auto-delete em 12h por padrão) e posta `[img]url[/img]` no site.
- **Stickers**: suportados PNG, GIF, APNG e Lottie (Nitro). Animados são convertidos pra GIF, cacheados em `./stickers/`, e enviados como `[img=150]url[/img]` (largura controlada por `STICKER_IMG_WIDTH`; `0` desativa o tamanho fixo).

**Site → Discord**:
- Cada mensagem do chat vira um **embed colorido** com:
  - **Cor**: do grupo do remetente no UNIT3D (ex: dourado pra Mico-Leão, vermelho pra notificações de sistema).
  - **Avatar** do remetente em 48×48 anexado ao embed (GIFs animados são preservados como `.gif`, estáticos como `.png`).
  - **Autor**: username do remetente.
  - **Footer**: horário da mensagem (`HH:MM:SS`).
  - **Imagem inline**: se a mensagem contém uma URL de imagem (regex), aparece como `embed.set_image`.
- **Delete-mirror via reação**: suas próprias mensagens (detectadas via `MY_USERNAME`/`MY_ALIASES`) recebem reação 🗑️ automática quando `SHOW_DELETE_BUTTON=true`. Você reagir com 🗑️ apaga em ambos os lados.
- **Quotes/citações** do site viram blockquote com prefixo `>` em cada linha (formato Markdown do Discord).
- **Emojis joypixels** do site são convertidos pra unicode nativo.

---

## 9. Cache de avatares (local)

O Discord usa **cache em disco** em `./avatars/` (diferente do Telegram que usa imgbb):

- Arquivos: `./avatars/{user_id}.png` ou `.gif`
- Índice: `discord_avatar_cache.json` com `{user_id: {hash, ext}}`
- Invalidação: TTL via mtime + hash SHA1 do conteúdo (igual ao Telegram).
  - Cache fresco dentro do TTL → retorna sem I/O.
  - Pós-TTL → baixa e compara hash; se igual, só renova mtime sem reprocessar.
  - Se hash mudou → Pillow redimensiona, salva, atualiza JSON.
- TTL controlado por `AVATAR_REVALIDATE_SECONDS` (default 1800s = 30min).

Pra limpar o cache: apague os arquivos em `./avatars/` e o `discord_avatar_cache.json`.

---

## 10. Troubleshooting

- **Bot conecta mas mensagens chegam vazias**: você esqueceu de habilitar **Message Content Intent** no portal.
- **Bot não apaga mensagens em sucesso**: falta permissão **Manage Messages** no canal.
- **Avatares não aparecem nos embeds**: cheque `bot_bridge.log` — provavelmente erro no download do `/authenticated-images/user-avatars/...` (cookie expirou) ou Pillow não conseguiu processar.
- **❌ no upload de imagem**: o imgbb pode estar rate-limitando ou a `IMGBB_API_KEY` não está configurada.
- **Bot não responde a `!ping`**: cheque se ele está conectado (`🔌 Discord conectado como ...` no log) e se o `DISCORD_CHANNEL_ID` aponta pro canal certo.
