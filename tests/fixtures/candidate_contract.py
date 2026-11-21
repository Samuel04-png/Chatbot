# Test-only source excerpts from Samuel04-png/rudo_medgemma, AGPL-3.0.
# Pinned commit: af2545c92aea2cbcda5c6d717f67598b386a373d
# Original module hashes recorded in candidate_provenance.json. Not production inference code.
# Copyright/license notices: CANDIDATE_LICENSE.txt; upstream repository LICENSE.txt.
# These function definitions are executed only with synthetic database/transport dependencies.

def save_user_conversation(sender, role, message, message_en=None):
    """message_en is the English version of the message, stored for pivoted languages."""
    db.add_message(sender, role, str(message), message_en)

def _split_for_whatsapp(text: str, limit: int=WHATSAPP_MAX_CHARS):
    if len(text) <= limit:
        return [text]
    parts, current = ([], '')
    for para in text.split('\n'):
        candidate = f'{current}\n{para}' if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = para
    if current:
        parts.append(current)
    return parts

def send(answer, sender, phone_id_val, message_en=None, save=True):
    """
    Send a WhatsApp text message.
    message_en: English version of the reply, stored with the history for MedGemma context.
    save=False for messages that should not enter the conversation history. Use it for every
    fixed UI text (welcome, greetings, resets, agent hand-offs, failures): history is what
    MedGemma sees, and local-language boilerplate in it makes the model answer in that language.
    """
    url = f'https://graph.facebook.com/v19.0/{phone_id_val}/messages'
    headers = {'Authorization': f'Bearer {wa_token}', 'Content-Type': 'application/json'}
    response = None
    for part in _split_for_whatsapp(answer):
        data = {'messaging_product': 'whatsapp', 'to': sender, 'type': 'text', 'text': {'body': part}}
        response = requests.post(url, headers=headers, json=data, timeout=15)
        logging.info(f'Send status to {sender}: {response.status_code}')
        if response.status_code >= 400:
            logging.error(f'Send failed: {response.text}')
    if save and normalize_phone(sender) not in AGENT_PHONES_NORM:
        save_user_conversation(sender, 'bot', answer, message_en)
    return response

def _history_for_model(sender, lang):
    """
    Stored history shaped for pairs_from_history.

    * The newest stored entry is the current user message. It is dropped here, and a blank
      sentinel entry is appended because pairs_from_history always drops the last entry.
      The current question is passed to the model separately.
    * For pivoted languages only entries that have an English version (message_en) are kept.
      Local-language text must never reach MedGemma: with a weak grasp of these languages it
      starts answering in broken Shona/Ndebele/etc. instead of English.
    * English users have no pivot, so their plain message text is used.
    """
    history = get_user_conversation(sender)[-HISTORY_ENTRIES_FOR_MODEL:]
    out = []
    for entry in history[:-1]:
        text = entry.get('message_en')
        if not text and lang == 'english':
            text = entry.get('message', '')
        if text and text.strip():
            out.append({**entry, 'message': text})
    out.append({'role': 'user', 'message': ''})
    return out

def pairs_from_history(entries, max_turns=2):
    """Turn the bot's stored conversation [{"role": "user"|"bot", "message": str}, ...] into
    [{"user":..., "model":...}] pairs. The newest entry is the current question, so it is dropped."""
    entries = (entries or [])[:-1]
    pairs, pending = ([], None)
    for e in entries:
        msg = (e.get('message') or '').strip()
        if not msg:
            continue
        if e.get('role') == 'user':
            pending = msg
        elif e.get('role') == 'bot' and pending and (len(msg) >= 20):
            pairs.append({'user': pending, 'model': msg})
            pending = None
    return pairs[-max_turns:]
