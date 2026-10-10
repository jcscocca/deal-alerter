"""Conservative published-spec matching. No inferred benchmark equivalence."""
import re

from .prebuilt import GPU, gpu_model


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def public_specs(value):
    return {k[:100]: v[:6000] for k, v in list(value.items())[:80]
            if isinstance(k, str) and isinstance(v, str)} if isinstance(value, dict) else {}


def cpu_models(value):
    value = value.replace("®", "").replace("™", "")
    value = re.sub(r"\bU([579])\s+(\d{3})", r"Ultra \1 \2", value, flags=re.I)
    value = re.sub(r"\bi([3579])\s*[- ]\s*(\d)", r"i\1-\2", value, flags=re.I)
    return {re.sub(r"\s+", " ", m.upper()) for m in re.findall(
        r"\b(?:[1-9]\d{3}(?:X3D|[XF])|i[3579]-\d{4,5}[A-Z]{0,3}|Ultra\s+[579]\s+\d{3}[A-Z]{0,2}(?:\s+Plus)?)\b", value, re.I)}


def capacities(value):
    return [int(float(n) * (1000 if unit.upper() == "TB" else 1))
            for n, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\b", value, re.I)]


def build_specs(title, specs, condition):
    fields = {normalized(k): v for k, v in public_specs(specs).items()}
    included = fields.get("includedcomponents", "")
    for line in included.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields["included" + normalized(k.strip('" '))] = v.strip('" ')
    selected = [v for k, v in fields.items() if k.startswith("selected")]
    cpu_text = " ".join([title, *selected, *(v for k,v in fields.items() if k in
                           ("cpu", "cpuname", "processor", "processormodel", "includedcpu"))])
    cpus = cpu_models(cpu_text)
    gpu_text = " ".join([title, *selected, *(v for k,v in fields.items() if k in
                           ("gpu", "gpuvgatype", "graphics", "includedgpu")),
                         "RTX " + fields.get("selectedgpu", "")])
    gpu = gpu_model(gpu_text)
    selected_gpus = {gpu_model("RTX " + m) for v in selected
                     for m in re.findall(r"\b(50[789]0(?:\s*(?:ti|super|d))?)\b", v, re.I)}
    published_gpus = {gpu_model("RTX " + m) for m in GPU.findall(gpu_text)} | selected_gpus
    if published_gpus != {gpu}:
        gpu = None
    ram_values = [v for k,v in fields.items() if k in ("ram", "memory", "memoryram", "memorysize", "memorycapacity",
                                                     "systemmemory", "selectedram", "selectedmemory", "includedram")]
    ram = []
    def expanded(value):
        return re.sub(r"\b(\d+)\s*[x×*]\s*(\d+)\s*GB\b", lambda m: f"{int(m[1])*int(m[2])}GB", value, flags=re.I)
    for value in ram_values:
        if not re.search(r"\b(?:up to|max(?:imum)?|supports?)\b", value, re.I):
            ram += capacities(expanded(value))
    for value in [title, *selected]:
        value = expanded(value)
        ram += [int(m[1]) for m in re.finditer(r"\b(\d+)\s*GB\s*(?:DDR[345]\b|RAM\b|memory\b)", value, re.I)
                if not re.search(r"(?:up to|max(?:imum)?|supports?)\s*$", value[max(0, m.start()-20):m.start()], re.I)]
    ram += [int(n) for v in selected for n in re.findall(r"\b(\d+)G\b", v, re.I)]
    types = set(re.findall(r"\bDDR[345]\b", " ".join([title, *ram_values, *selected, fields.get("memorytype", "")]).upper()))
    ssd = []
    ambiguous_storage = False
    for value in [title, *selected]:
        matches = re.findall(r"\b\d+(?:\.\d+)?\s*(?:TB|GB)\s*(?:(?:Gen[345]|NVMe|M\.2|PCIe[\d. ]*|SATA)\s+)*SSD\b", value, re.I)
        ambiguous_storage |= len(matches) > 1 or bool(re.search(r"\b\d+\s*[x×*]\s*\d+(?:\.\d+)?\s*(?:TB|GB).*?SSD\b|\b(?:HDD|hard drive)\b", value, re.I))
        ssd += [n for m in matches for n in capacities(m)]
    for k, v in fields.items():
        if k in ("ssd", "includedssd", "solidstatedrive", "selectedstorage", "selectedssd"):
            numbers = capacities(v)
            ambiguous_storage |= len(numbers) != 1 or bool(re.search(r"[x×*+]|\bHDD\b", v, re.I))
            ssd += numbers
    ssd += [int(n)*1000 for v in selected for n in re.findall(r"\b(\d+)T\b", v, re.I)]
    for value in selected:
        selected_ssd = re.findall(r"\b(\d+(?:\.\d+)?)\s*TB\b", value, re.I)
        ambiguous_storage |= len(selected_ssd) > 1
        ssd += [int(float(n)*1000) for n in selected_ssd]
    condition = normalized(condition)
    condition = {"new": "new", "used": "used", "refurbished": "refurbished", "openbox": "open_box"}.get(condition)
    one = lambda values: next(iter(set(values))) if len(set(values)) == 1 else None
    core = {"gpu": gpu, "cpu": one(cpus), "ram_gb": one(ram), "ram_type": one(types),
            "ssd_gb": None if ambiguous_storage else one(ssd), "condition": condition}
    issues = [f"{name} missing or conflicting" for key,name in
              (("gpu","Exact GPU"),("cpu","Exact CPU"),("ram_gb","RAM capacity"),("ram_type","RAM type"),
               ("ssd_gb","Single SSD capacity"),("condition","Condition")) if not core[key]]
    if re.search(r"\b(?:up to|select your|choose your|various configurations|case only|case for|enclosure)\b", title, re.I):
        issues.append("Selected configuration is ambiguous")
    details = {}
    for name, keys, pattern in (
        ("Power supply", ("powersupply", "psu", "includedpowersupply"), r"\b\d{3,4}W\b[^,;]{0,35}"),
        ("Motherboard", ("motherboard", "includedmotherboard"), r"\b[ABHXZ]\d{3}[^,;]{0,20}(?:Board|Motherboard)\b"),
        ("Cooling", ("cpucooler", "cooling", "includedcpucooler"), r"\b\d{2,3}\s*(?:mm\s+)?(?:ARGB\s+)?AIO\b"),
        ("Warranty", ("warranty", "includedwarranty"), r"\b\d+[- ]year\s+(?:parts[^,;]*|warranty)"),
    ):
        match = re.search(pattern, title, re.I)
        details[name] = next((fields[k][:180] for k in keys if fields.get(k)), match[0] if match else "Not published")
    return {"core": core, "key": tuple(core.values()) if not issues else None, "issues": issues,
            "details": details, "model": fields.get("model", ""),
            "variable_parts": bool(re.search(r"brands? may vary|parts? may vary|components? may vary", title+" "+included, re.I))}
