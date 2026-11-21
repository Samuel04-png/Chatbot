(() => {
  const PRIORITY = {
    URGENT: { id: 'URGENT', label: 'Urgent', rank: 3, badge: 'badge-danger', note: 'Agent follow-up' },
    HIGH: { id: 'HIGH', label: 'High', rank: 2, badge: 'badge-warning', note: 'Immediate provider contact' },
    HIGH_MODERATE: { id: 'HIGH-MODERATE', label: 'High-moderate', rank: 1, badge: 'badge-accent', note: 'Same-day contact' }
  };

  const CATEGORIES = [
    {
      id: 1,
      name: 'Pregnancy Loss & Bleeding',
      priority: PRIORITY.URGENT,
      intents: [
        { label: 'Vaginal bleeding during pregnancy', patterns: [/vaginal\s*bleed/i, /bleed(?:ing)?\s+(?:during|in)\s+pregnan/i, /spotting\s+(?:during|in)\s+pregnan/i] },
        { label: 'Heavy bleeding/hemorrhage', patterns: [/(?<!postpartum\s)heavy\s*bleed/i, /(?<!postpartum\s)ha?emorrhag/i, /bleeding\s+(?:a\s+lot|heavily|profusely)(?!.*(?:after\s+(?:birth|delivery)|postpartum))/i] },
        { label: 'Miscarriage symptoms', patterns: [/miscarriage/i, /losing\s+(?:the\s+)?(?:baby|pregnancy)/i, /pregnancy\s+loss/i] },
        { label: 'Ectopic pregnancy concerns', patterns: [/ectopic/i] },
        { label: 'Molar pregnancy indicators', patterns: [/molar\s+pregnan/i, /gestational\s+trophoblastic/i] },
        { label: 'Placental abruption symptoms', patterns: [/placental\s+abruption/i, /abruption/i, /placenta\s+(?:coming\s+)?(?:away|detached|detach)/i] },
        { label: 'Threatened miscarriage', patterns: [/threatened\s+miscarriage/i] },
        { label: 'Recurrent pregnancy loss', patterns: [/recurrent\s+(?:pregnancy\s+)?loss/i, /multiple\s+miscarriages/i] }
      ]
    },
    {
      id: 2,
      name: 'Hypertensive Crises & Preeclampsia',
      priority: PRIORITY.URGENT,
      intents: [
        { label: 'Severe headaches in pregnancy', patterns: [/severe\s+headache/i, /bad\s+headache/i, /migraine\s+(?:in|during)\s+pregnan/i, /headache.*pregnan/i, /pregnan.*headache/i] },
        { label: 'Visual disturbances/blurred vision', patterns: [/blur(?:red)?\s+vision/i, /seeing\s+spots/i, /visual\s+disturb/i, /flashing\s+lights/i, /can't\s+see\s+(?:well|clearly)/i] },
        { label: 'Chest pain during pregnancy', patterns: [/chest\s+pain/i, /pain\s+in\s+(?:my\s+)?chest/i] },
        { label: 'Sudden swelling/edema', patterns: [/sudden\s+swell/i, /swelling\s+(?:in|of)\s+(?:my\s+)?(?:face|hands|feet|legs)/i, /\bedema\b/i, /puffy\s+face/i] },
        { label: 'Blood pressure concerns (stated high readings)', patterns: [/high\s+(?:blood\s+)?pressure/i, /\bBP\b.*(?:high|elevated|\d{2,3}\/\d{2,3})/i, /blood\s+pressure.*(?:high|elevated|\d{2,3})/i, /hypertension/i] },
        { label: 'Preeclampsia/eclampsia symptoms', patterns: [/pre[- ]?eclampsi/i, /\beclampsi/i] },
        { label: 'HELLP syndrome indicators', patterns: [/\bHELLP\b/i] }
      ]
    },
    {
      id: 3,
      name: 'Infection & Fever',
      priority: PRIORITY.URGENT,
      intents: [
        { label: 'High fever in pregnancy', patterns: [/high\s+fever/i, /fever\s+(?:of\s+)?(?:39|40|104|103)/i, /fever.*pregnan/i, /pregnan.*fever/i, /temperature\s+(?:is\s+)?(?:very\s+)?high/i] },
        { label: 'Flu-like symptoms during pregnancy', patterns: [/flu[- ]?like/i, /body\s+aches.*pregnan/i, /chills.*pregnan/i] },
        { label: 'Urinary tract infection complications', patterns: [/\bUTI\b/i, /urinary\s+tract\s+infection/i, /burning\s+(?:when|while)\s+(?:I\s+)?(?:pee|urinat)/i, /pain(?:ful)?\s+urinat/i] },
        { label: 'Sepsis concerns', patterns: [/\bsepsis\b/i, /blood\s+infection/i, /septic/i] },
        { label: 'COVID-19 in pregnant patients', patterns: [/covid/i, /coronavirus/i] },
        { label: 'Listeria/food-borne illness exposure', patterns: [/listeria/i, /food[- ]?borne/i, /food\s+poisoning/i] }
      ]
    },
    {
      id: 4,
      name: 'Mental Health Crisis',
      priority: PRIORITY.HIGH,
      intents: [
        { label: 'Active suicidal ideation', patterns: [/suicid/i, /kill\s+myself/i, /end\s+my\s+life/i, /want\s+to\s+die/i, /don't\s+want\s+to\s+live/i] },
        { label: 'Severe postpartum depression', patterns: [/postpartum\s+depression/i, /\bPPD\b/i, /severe\s+depression/i] },
        { label: 'Postpartum psychosis symptoms', patterns: [/postpartum\s+psychosis/i, /hearing\s+voices/i, /seeing\s+things\s+that\s+aren't/i] },
        { label: 'Maternal harm ideation', patterns: [/hurt\s+myself/i, /harm\s+myself/i, /self[- ]?harm/i] },
        { label: 'Harmful thoughts toward baby', patterns: [/hurt\s+(?:the\s+|my\s+)?baby/i, /harm\s+(?:the\s+|my\s+)?baby/i, /thoughts?\s+(?:of|about)\s+harming\s+(?:the\s+|my\s+)?baby/i] },
        { label: 'Severe anxiety attacks', patterns: [/panic\s+attack/i, /severe\s+anxiety/i, /anxiety\s+attack/i, /can't\s+breathe.*anxiety/i] },
        { label: 'Substance use during pregnancy', patterns: [/using\s+drugs/i, /drinking\s+alcohol.*pregnan/i, /substance\s+use/i, /taking\s+drugs.*pregnan/i] }
      ]
    },
    {
      id: 5,
      name: 'Severe Pain & Emergencies',
      priority: PRIORITY.HIGH,
      intents: [
        { label: 'Acute abdominal pain', patterns: [/severe\s+(?:stomach|abdominal|belly)\s+pain/i, /acute\s+(?:abdominal|stomach)\s+pain/i, /unbearable\s+(?:stomach|belly|abdominal)\s+pain/i] },
        { label: 'Severe back pain (potential kidney/appendix issue)', patterns: [/severe\s+back\s+pain/i, /kidney\s+pain/i, /appendix/i, /pain\s+in\s+(?:my\s+)?(?:lower\s+)?back/i] },
        { label: 'Labor pain onset before term', patterns: [/labor\s+pain/i, /contractions?\s+(?:before|early|preterm)/i, /going\s+into\s+labor\s+early/i] },
        { label: 'Chest/rib pain', patterns: [/rib\s+pain/i, /pain\s+in\s+(?:my\s+)?ribs/i] },
        { label: 'Fainting/syncope episodes', patterns: [/faint(?:ed|ing)?/i, /\bsyncope\b/i, /passed\s+out/i, /blacked\s+out/i, /lost\s+consciousness/i] },
        { label: 'Severe leg swelling (DVT concern)', patterns: [/leg\s+swell/i, /\bDVT\b/i, /deep\s+vein/i, /one\s+leg\s+(?:is\s+)?(?:swollen|swelling)/i, /calf\s+pain/i] },
        { label: 'Sudden onset severe symptoms', patterns: [/sudden(?:ly)?\s+(?:severe|worst|extreme)/i, /worst\s+pain\s+(?:of\s+my\s+life|ever)/i] },
        { label: 'Trauma/injury during pregnancy', patterns: [/trauma/i, /car\s+accident/i, /fell\s+(?:down|hard)|fall(?:en)?\s+(?:down|hard)/i, /injured.*pregnan/i, /pregnan.*injur/i, /hit\s+(?:in\s+)?(?:my\s+)?(?:stomach|belly|abdomen)/i] }
      ]
    },
    {
      id: 6,
      name: 'Fetal Concerns',
      priority: PRIORITY.HIGH,
      intents: [
        { label: 'No fetal movement/decreased movement', patterns: [/no\s+(?:fetal\s+)?movement/i, /baby\s+(?:isn't|is not|not)\s+mov(?:e|ing)/i, /decreased\s+(?:fetal\s+)?movement/i, /less\s+(?:baby\s+)?(?:kick|movement)/i, /haven't\s+felt\s+(?:the\s+)?baby/i] },
        { label: 'Fetal distress indicators', patterns: [/fetal\s+distress/i, /baby\s+(?:is\s+)?(?:in\s+)?distress/i] },
        { label: 'Cord prolapse concerns', patterns: [/cord\s+prolapse/i, /umbilical\s+cord\s+(?:coming|hanging|out)/i] },
        { label: 'Intrauterine growth restriction (IUGR)', patterns: [/\bIUGR\b/i, /intrauterine\s+growth/i, /baby\s+(?:is\s+)?(?:too\s+)?small/i, /growth\s+restriction/i] },
        { label: 'Signs of premature labor', patterns: [/premature\s+labou?r/i, /preterm\s+labou?r/i, /going\s+into\s+labou?r\s+early/i] },
        { label: 'Stillbirth concerns', patterns: [/stillbirth/i, /stillborn/i, /baby\s+(?:has\s+)?died/i, /no\s+heartbeat/i] }
      ]
    },
    {
      id: 7,
      name: 'Postpartum Emergencies',
      priority: PRIORITY.HIGH_MODERATE,
      intents: [
        { label: 'Postpartum hemorrhage/heavy bleeding', patterns: [/postpartum\s+(?:ha?emorrhage|bleed)/i, /heavy\s+bleeding\s+after\s+(?:birth|delivery)/i, /bleeding\s+(?:a\s+lot|heavily)\s+after/i, /\bPPH\b/i] },
        { label: 'Severe postpartum pain', patterns: [/severe\s+(?:pain\s+)?after\s+(?:birth|delivery)/i, /postpartum\s+(?:severe\s+)?pain/i] },
        { label: 'Signs of postpartum infection', patterns: [/postpartum\s+infection/i, /infection\s+after\s+(?:birth|delivery)/i, /smelly\s+(?:discharge|lochia)/i] },
        { label: 'Postpartum blood clots (DVT/PE)', patterns: [/blood\s+clot/i, /pulmonary\s+embolism/i, /\bPE\b.*(?:clot|lung|breath)/i, /clot.*(?:leg|lung)/i] },
        { label: 'Mastitis with systemic symptoms', patterns: [/mastitis/i, /breast\s+(?:infection|abscess)/i, /fever.*breast/i, /breast.*fever/i] }
      ]
    },
    {
      id: 8,
      name: 'Medication & Substance Concerns',
      priority: PRIORITY.HIGH_MODERATE,
      intents: [
        { label: 'Accidental medication overdose', patterns: [/overdose/i, /took\s+too\s+many/i, /accidental(?:ly)?\s+(?:took|ingested)/i] },
        { label: 'Unsafe medication use in pregnancy', patterns: [/unsafe\s+(?:medication|medicine|drug)/i, /should(?:n't| not)\s+(?:take|have\s+taken).*(?:pregnan|baby)/i, /is\s+.*(?:safe|unsafe)\s+(?:in|during)\s+pregnan/i] },
        { label: 'Substance abuse/withdrawal', patterns: [/substance\s+abuse/i, /withdrawal/i, /addicted/i, /detox/i] },
        { label: 'Drug interaction concerns (high-risk combinations)', patterns: [/drug\s+interaction/i, /interaction\s+(?:with|between)\s+(?:my\s+)?(?:meds|medications|drugs)/i, /mixing\s+(?:meds|medications|drugs)/i] }
      ]
    },
    {
      id: 9,
      name: 'Delivery & Labor Complications',
      priority: PRIORITY.HIGH_MODERATE,
      intents: [
        { label: 'Premature labor onset', patterns: [/premature\s+(?:labou?r|delivery|birth)/i, /preterm\s+(?:labou?r|delivery|birth)/i, /labou?r\s+started\s+early/i] },
        { label: 'Placental complications', patterns: [/placenta\s+previa/i, /retained\s+placenta/i, /placental\s+complicat/i, /problems?\s+with\s+(?:the\s+)?placenta/i] },
        { label: 'Umbilical cord issues', patterns: [/umbilical\s+cord/i, /cord\s+(?:around|wrapped|nuchal)/i, /nuchal\s+cord/i] }
      ]
    }
  ];

  function messageText(message) {
    if (!message) return '';
    return String(message.message || message.text || message.content || '').trim();
  }

  function assessText(text) {
    const raw = String(text || '');
    if (!raw.trim()) return null;

    let best = null;
    CATEGORIES.forEach((category) => {
      category.intents.forEach((intent) => {
        const matched = intent.patterns.some((pattern) => pattern.test(raw));
        if (!matched) return;
        const candidate = {
          categoryId: category.id,
          category: category.name,
          intent: intent.label,
          priority: category.priority.id,
          priorityLabel: category.priority.label,
          priorityRank: category.priority.rank,
          badge: category.priority.badge,
          note: category.priority.note
        };
        if (!best || candidate.priorityRank > best.priorityRank) best = candidate;
      });
    });
    return best;
  }

  function assessConversation(messages) {
    const list = Array.isArray(messages) ? messages : [];
    let best = null;
    list.forEach((message) => {
      const role = String(message.role || '').toLowerCase();
      if (role && role !== 'user') return;
      const hit = assessText(messageText(message));
      if (!hit) return;
      if (!best || hit.priorityRank > best.priorityRank) best = hit;
    });
    return best;
  }

  function toPatientId(phoneOrKey) {
    const raw = String(phoneOrKey || '');
    if (/^DH-[0-9A-Z]{4}-[0-9A-Z]{4}$/i.test(raw)) return raw.toUpperCase();
    const fromKey = raw.startsWith('conversation:') ? raw.slice(13) : raw;
    const digits = fromKey.replace(/\D/g, '');
    if (!digits) return 'DH-0000-XXXX';
    let hash = 2166136261;
    for (let i = 0; i < digits.length; i++) {
      hash ^= digits.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    const num = String(Math.abs(hash) % 10000).padStart(4, '0');
    const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    let suffix = '';
    let n = Math.abs(hash >>> 0);
    for (let i = 0; i < 4; i++) {
      suffix += alphabet[n % alphabet.length];
      n = Math.floor(n / alphabet.length);
    }
    return `DH-${num}-${suffix}`;
  }

  window.RiskTriage = {
    PRIORITY,
    CATEGORIES,
    assessText,
    assessConversation,
    toPatientId,
    messageText
  };
})();
