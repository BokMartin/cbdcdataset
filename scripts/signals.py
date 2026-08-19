import re

ENDGOALS = [
    "cash_substitution", "financial_inclusion", "sovereignty_competition",
    "payment_modernization", "monetary_transmission", "state_control",
]

KEYWORDS = {
    "cash_substitution": [
        r"declin\w* (in |of )?cash", r"cash (usage|use|in circulation|decline)",
        r"falling cash", r"reduced? cash", r"less cash", r"disappear\w* cash",
        r"public money", r"central bank money", r"monetary anchor", r"\banchor\b",
        r"cash-?like", r"like cash", r"equivalent to cash", r"analogous to cash",
        r"complement\w* (to )?cash", r"alongside cash", r"not (to )?replace cash",
        r"legal tender", r"physical cash", r"continued access to (central bank|public)",
        r"store of value", r"banknote", r"banknotes? and coins?", r"digital (form of )?cash",
        r"supplement\w* (to )?cash", r"coexist\w* with cash",
    ],
    "financial_inclusion": [
        r"unbank\w+", r"under-?bank\w+", r"financial inclusion", r"financially excluded",
        r"financial exclusion", r"access to (financial|payment)", r"\brural\b", r"remote area",
        r"underserved", r"low-?cost", r"affordab\w+", r"simplif\w+ (kyc|onboard)",
        r"basic (account|wallet)", r"digital divide", r"last mile", r"inclusi\w+",
        r"reach\w* the (poor|unbanked)", r"low-?income", r"vulnerab\w+", r"disabilit\w+",
        r"without (a |any )?bank account", r"financial literacy", r"elderly",
    ],
    "sovereignty_competition": [
        r"stablecoin", r"crypto-?(asset|currenc)", r"bitcoin", r"big-?tech",
        r"private (money|currenc|digital money)", r"foreign cbdc", r"foreign currenc",
        r"dollar\w*ation", r"currency substitution", r"monetary sovereignty",
        r"strategic autonomy", r"geopolit\w+", r"payment autonomy", r"global stablecoin",
        r"\blibra\b", r"\bdiem\b", r"facebook", r"sovereign\w*",
        r"resilien\w* of the (currency|payment)", r"dependen\w* on (foreign|private)",
        r"competit\w* (currenc|pressure)",
    ],
    "payment_modernization": [
        r"instant\w*", r"real-?time payment", r"interoperab\w+", r"settlement efficiency",
        r"payment efficiency", r"faster payment", r"fast payment", r"cross-?border",
        r"moderniz\w+", r"\befficien\w+", r"fragment\w+ (of )?payment", r"\bpsp\b",
        r"payment service provider", r"innovati\w+ payment", r"competiti\w* payment",
        r"card scheme", r"card network", r"global card", r"international card", r"\bvisa\b",
        r"mastercard", r"four-?party scheme", r"non-?european (card|scheme|provider|payment)",
        r"foreign (card|payment) (scheme|network|provider|system)",
        r"dependen\w* on (international|global|foreign|non-european|major) (card|payment|scheme)",
        r"payment (system )?resilience", r"frictionless", r"24/7|around the clock",
        r"innovati\w+ payment|payment innovation", r"point[- ]of[- ]sale|\bpos\b", r"qr code",
        r"e-?commerce", r"micropayment", r"payment landscape", r"competition in (the )?payment",
    ],
    "monetary_transmission": [
        r"interest-?bearing", r"remunerat\w+", r"interest rate", r"negative rate",
        r"monetary policy", r"pass-?through", r"monetary transmission", r"\btransmission\b",
        r"holding limit", r"disintermediation", r"bank disintermediation", r"policy rate",
        r"tiered remuneration", r"financial stability", r"bank deposit", r"capital flight",
        r"run on (the )?bank", r"unremunerated", r"zero (interest|remuneration)",
        r"deposit outflow", r"holding cap", r"tiering", r"conversion limit",
    ],
    "state_control": [
        r"traceab\w+", r"\bmonitor\w+", r"surveillance", r"law enforcement", r"sanction\w+",
        r"managed anonymity", r"(controllable|manageable|managed) anonymity", r"\baml\b", r"\bcft\b",
        r"money laundering", r"terroris\w+ financ", r"illicit", r"tax evasion",
        r"transaction monitoring", r"complian\w+", r"identif\w+", r"audit\w+ trail",
        r"fully auditable", r"surveillab\w+", r"oversight", r"suspicious (transaction|activity)",
        r"financial intelligence", r"record\w* of (all )?transactions?", r"financial crime",
    ],
}

CODE_SIGNAL = {
    "PRIV.OFF": {"cash_substitution": 1.0, "financial_inclusion": 0.6},
    "PRIV.ANON": {"cash_substitution": 0.8},
    "PRIV.MIN": {"cash_substitution": 0.5},
    "PRIV.PET": {"cash_substitution": 0.4},
    "KYC.TIER": {"financial_inclusion": 1.0},
    "KYC.INTERMED": {"payment_modernization": 0.7},
    "AML.LIMIT": {"monetary_transmission": 0.8},
    "TECH.DLT": {"payment_modernization": 0.5, "sovereignty_competition": 0.3},
    "AML.MON": {"state_control": 1.0},
    "AML.FATF": {"state_control": 0.8},
    "AML.RISK": {"state_control": 0.6},
    "KYC.IDV": {"state_control": 0.8},
    "PRIV.CB.visibility.transparent": {"state_control": 0.9},
    "PROG.remuneration_yes": {"monetary_transmission": 0.8},
    "PROG.remuneration_no": {"monetary_transmission": 0.8},
    "PROG.remuneration_considered": {"monetary_transmission": 0.8},
    "PROG.restriction": {"state_control": 0.8},
    "TECH.TOKEN": {"payment_modernization": 0.5, "sovereignty_competition": 0.3},
    "CASH.relation": {"cash_substitution": 0.8},
    "INTEROP.domestic": {"payment_modernization": 0.5, "monetary_transmission": 0.3},
    "INTEROP.crossborder": {"sovereignty_competition": 0.5, "payment_modernization": 0.3},
    "ACCESS.universal": {"financial_inclusion": 0.8},
    "STAB.disintermediation": {"monetary_transmission": 0.8},
    "OPS.resilience": {"payment_modernization": 0.5},
    "ADOPT.experience": {"payment_modernization": 0.5, "financial_inclusion": 0.3},
    "SYS.design": {"payment_modernization": 0.3},
}


def code_root(code):
    code = str(code or "")
    if code.startswith("PRIV.CB.visibility"):
        return code
    parts = code.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else code


def keyword_hits(text, patterns):
    text = str(text or "").lower()
    return sum(bool(re.search(pattern, text)) for pattern in patterns)
