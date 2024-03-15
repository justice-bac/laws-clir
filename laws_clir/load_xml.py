import os

from llama_index.node_parser import SentenceSplitter
from llama_index.schema import TextNode
from lxml import etree as ET


def law_xml_to_nodes(file_path):
    d = get_dict_from_xml(file_path)
    num_sections = len(d["all_chunkable_sections"])
    nodes = [section_to_nodes(section) for section in d["all_chunkable_sections"]]
    # Flatten nodes
    nodes = [node for sublist in nodes for node in sublist]
    file_id = d["title_str"]
    return nodes, file_id, num_sections


def section_to_nodes(section, chunk_size=1024, chunk_overlap=100):
    if chunk_size < 50:
        raise ValueError("Chunk size must be at least 50 tokens.")
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    # Split the text into chunks
    chunks = splitter.split_text(section["text"])
    # Create a node from each chunk
    nodes = []
    for i, chunk in enumerate(chunks):
        nodes.append(
            TextNode(
                text=chunk,
                metadata={
                    # "section_id": section["section_id"],
                    # "parent_id": section["parent_id"],
                    "file_id": section["doc_title"],
                    "section": section["section_str"],
                    "headings": section["heading_str"],
                    # "index": i,
                    # "doc_id": section["doc_id"],
                    # "in_force_start_date": section["in_force_start_date"],
                    # "last_amended_date": section["last_amended_date"],
                    # "lims_id": section["lims_id"],
                    # "marginal_note": section["marginal_note"],
                    # "internal_refs": section["internal_refs"],
                    # "external_refs": section["external_refs"],
                },
            )
        )
    return nodes

def _get_text(element):
    return element.text if element is not None else None


def _get_link(element):
    return (
        element.attrib["link"]
        if element is not None and "link" in element.attrib.keys()
        else None
    )


def _get_joined_text(
    element,
    exclude_tags=["MarginalNote", "Label", "OriginatingRef"],
    break_tags=[
        "Provision",
        "Subsection",
        "Paragraph",
        "Definition",
        "row",
        "TableGroup",
        "HistoricalNote",
        "MarginalNote",
    ],
    double_break_tags=["Subsection", "TableGroup"],
    pipe_tags=["entry"],
    em_tags=["DefinedTermEn", "DefinedTermFr", "XRefExternal", "XRefInternal", "Emphasis"],
    strong_tags=["MarginalNote", "TitleText"],
    underline_tags=[],
):
    # TODO: Improve table parsing
    def stylized_text(text, tag):
        if tag in em_tags:
            return f"*{text}*"
        if tag in strong_tags:
            return f"**{text}**"
        if tag in underline_tags:
            return f"__{text}__"
        # if tag in strike_tags:
        #     return f"~~{text}~~"
        return text

    all_text = []
    exclude_tags = exclude_tags.copy()
    for e in element.iter():
        if e.tag in exclude_tags:
            exclude_tags.remove(e.tag)
            continue
        if e.text and e.text.strip():
            all_text.append(stylized_text(e.text.strip(), e.tag))
        if e.tail and e.tail.strip():
            all_text.append(e.tail.strip())
        if e.tag in break_tags:
            all_text.append("\n")
        elif e.tag in double_break_tags:
            all_text.append("\n\n")
        if e.tag in pipe_tags:
            all_text.append("|")
        if e.tag == "tbody":
            all_text.append("\n<tbody>")
    text = (
        " ".join(all_text)
        .replace(" \n ", "\n")
        .strip()
        .replace("\u2002", " ")
        .replace("( ", "(")
        .replace(" )", ")")
        .replace(" .", ".")
        .replace("* ;", "*;")
        .replace("* ,", "*,")
        .replace("* .", "*.")
        .strip()
    )
    # When a line ends in a pipe, it should also start with a pipe and space
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        if line.endswith("|"):
            lines[i] = "| " + line
        # Replace the <tbody> tag with | --- | --- | --- | etc. for tables
        if line == "<tbody>" and i > 0 and lines[i - 1].strip().endswith("|"):
            lines[i] = "| --- " * (len(lines[i - 1].split("|")) - 2) + "|"
        elif line == "<tbody>":
            lines[i] = ""
    text = "\n".join(lines)
    return text


def get_dict_from_xml(xml_filename):
    # Extract a JSON serializable dictionary from a act/regulation XML file
    dom = ET.parse(xml_filename)
    root = dom.getroot()
    # French regulations have slightly different filenames, but we want a unique ID
    # to link the English and French versions
    filename = os.path.basename(xml_filename).replace(".xml", "")
    # Replace "DORS-" with "SOR-", "TR-" with "SI-" and "_ch." with "_c."
    eng_id = (
        filename.replace("DORS-", "SOR-").replace("TR-", "SI-").replace("_ch.", "_c.")
    )
    d = {
        "id": eng_id,
        "lang": os.path.basename(os.path.dirname(os.path.dirname(xml_filename))),
        "filename": filename,
        "type": "act" if root.tag == "Statute" else "regulation",
        "short_title": _get_text(root.find(".//ShortTitle")),
        "long_title": _get_text(root.find(".//LongTitle")),
        "bill_number": _get_text(root.find(".//BillNumber")),
        "instrument_number": _get_text(root.find(".//InstrumentNumber")),
        "consolidated_number": _get_text(root.find(".//ConsolidatedNumber")),
        "last_amended_date": root.attrib.get(
            "{http://justice.gc.ca/lims}lastAmendedDate", None
        ),
        "current_date": root.attrib.get(
            "{http://justice.gc.ca/lims}current-date", None
        ),
        "in_force_start_date": root.attrib.get(
            "{http://justice.gc.ca/lims}inforce-start-date", None
        ),
        "enabling_authority": {
            "link": _get_link(root.find(".//EnablingAuthority/XRefExternal")),
            "text": _get_text(root.find(".//EnablingAuthority/XRefExternal")),
        },
        "preamble": get_preamble(root),
        "sections": [
            section
            for section in [
                get_section(section) for section in root.findall(".//Section")
            ]
            if section is not None
        ],
        "schedules": [
            schedule
            for schedule in [
                get_schedule(schedule) for schedule in root.findall(".//Schedule")
            ]
            if schedule is not None
        ],
    }
    # Aggregate all internal and external references and count instances of each
    for ref_name in ["internal_refs", "external_refs"]:
        ref_list = [
            ref
            for section in d["sections"]
            for ref in section[ref_name]
            if ref["link"] is not None
        ]
        ref_list_set = set([ref["link"] for ref in ref_list])
        d[ref_name] = [
            {
                "link": link,
                "count": len([ref for ref in ref_list if ref["link"] == link]),
            }
            for link in ref_list_set
        ]
    # Some pretty-print and/or unique versions of the fields
    d["doc_id"] = f'{d["id"]}_{d["lang"]}'
    d["title_str"] = d["short_title"] if d["short_title"] else d["long_title"]
    for section in d["sections"]:
        section["section_id"] = f'{d["doc_id"]}_section_{section["id"]}'
        section["heading_str"] = get_heading_str(section)
        section["section_str"] = f"Section {section['id']}"
        section["all_str"] = "\n".join(
            [
                d["title_str"],
                section["section_str"],
                section["heading_str"],
                section["text"],
            ]
        )
        for subsection in section["subsections"]:
            subsection[
                "section_id"
            ] = f'{d["doc_id"]}_subsection_{section["id"]}{subsection["id"]}'
            subsection["parent_id"] = section["section_id"]
            subsection["heading_str"] = get_heading_str(subsection)
            subsection[
                "section_str"
            ] = f"Sub{section['section_str'].lower()}{subsection['id']}"
            subsection["all_str"] = "\n".join(
                [
                    d["title_str"],
                    subsection["section_str"],
                    subsection["heading_str"],
                    subsection["text"],
                ]
            )
    for schedule in d["schedules"]:
        schedule["section_id"] = f'{d["doc_id"]}_schedule_{schedule["id"]}'
        schedule["heading_str"] = ""
        schedule["section_str"] = schedule['id']
        schedule["all_str"] = "\n".join(
            [
                d["title_str"],
                (schedule["id"] if schedule["id"] else "Schedule"),
                "",
                schedule["text"],
            ]
        )
    # Finally, the preamble also needs a "all_str" field
    if d["preamble"]:
        d["preamble"][0]["section_id"] = f'{d["doc_id"]}_preamble'
        d["preamble"][0]["heading_str"] = get_heading_str(d["preamble"][0])
        d["preamble"][0]["section_str"] = "Preamble"
        d["preamble"][0]["all_str"] = "\n".join(
            [
                d["title_str"],
                "Preamble",
                "",
                d["preamble"][0]["text"],
            ]
        )
        for section in d["preamble"][0]["subsections"]:
            section["section_id"] = f'{d["doc_id"]}_preamble_provision_{section["id"]}'
            section["parent_id"] = d["preamble"][0]["section_id"]
            section["heading_str"] = get_heading_str(section)
            section["section_str"] = f"Preamble provision {section['id']}"
            section["all_str"] = "\n".join(
                [
                    d["title_str"],
                    section["section_str"],
                    section["heading_str"],
                    section["text"],
                ]
            )
    # Add a list of all sections, including preamble and schedules and subsections
    d["all_chunkable_sections"] = []
    keep_keys = ["section_id", "parent_id", "section_str", "heading_str", "text", "id", "marginal_note", "in_force_start_date", "last_amended_date", "internal_refs", "external_refs", "lims_id"]
    if d["preamble"]:
        # Keep only the keys we need from d["preamble"][0]
        d["all_chunkable_sections"].append({k: v for k, v in d["preamble"][0].items() if k in keep_keys})
        for p in d["preamble"][0]["subsections"]:
            d["all_chunkable_sections"].append({k: v for k, v in p.items() if k in keep_keys})
    for s in d["sections"]:
        d["all_chunkable_sections"].append({k: v for k, v in s.items() if k in keep_keys})
        for ss in s["subsections"]:
            d["all_chunkable_sections"].append({k: v for k, v in ss.items() if k in keep_keys})
    for s in d["schedules"]:
        d["all_chunkable_sections"].append({k: v for k, v in s.items() if k in keep_keys})
    for i, s in enumerate(d["all_chunkable_sections"]):
        s["doc_id"] = d["doc_id"]
        s["doc_title"] = d["title_str"]
        s["index"] = i
        if s["marginal_note"]:
            s["text"] = f"**{s['marginal_note']}**\n{s['text']}"
    return d


def get_heading_str(section):
    # heading_str = ""
    # for i, heading in enumerate(section["headings"]):
    #     heading_str += f"{' ' * (i+2)}{heading}\n"
    # if section["marginal_note"]:
    #     # heading_str += f"{' ' * (len(section['headings'])+2)}{section['marginal_note']}\n"
    #     heading_str += f"\n**{section['marginal_note']}**"
    # return heading_str
    return " > ".join(section["headings"])


def get_section(section):
    # If the section has an ancestor <Schedule> tag, skip it
    if section.xpath(".//Schedule"):
        return None
    return {
        "id": _get_text(section.find("Label")),
        "headings": get_headings(section),
        "marginal_note": _get_text(section.find("MarginalNote")),
        "text": _get_joined_text(section),
        "in_force_start_date": section.attrib.get(
            "{http://justice.gc.ca/lims}inforce-start-date", None
        ),
        "last_amended_date": section.attrib.get(
            "{http://justice.gc.ca/lims}lastAmendedDate", None
        ),
        "subsections": [
            get_section(subsection) for subsection in section.findall(".//Subsection")
        ],
        "external_refs": get_external_xrefs(section),
        "internal_refs": get_internal_xrefs(section),
        "lims_id": section.attrib.get("{http://justice.gc.ca/lims}id", None),
    }


def get_external_xrefs(section):
    # External references have an explicit link attribute
    return [
        {
            "link": xref.attrib.get("link", None),
            "reference_type": xref.attrib.get("reference-type", None),
            "text": xref.text,
        }
        for xref in section.findall(".//XRefExternal")
    ]


def get_internal_xrefs(section):
    # Internal references are always a section number which is the text
    return [
        {
            "link": xref.text,
        }
        for xref in section.findall(".//XRefInternal")
    ]


def get_preamble(root):
    # Returns an array with a single element, the preamble, or no elements
    # so that it can be easily prepended to the sections array
    preamble = root.find(".//Preamble")
    if preamble is None:
        return []
    preamble.findall(".//Provision")
    return [{
        "id": "preamble",
        "headings": get_headings(preamble),
        "marginal_note": None,
        "text": _get_joined_text(preamble),
        "in_force_start_date": preamble.attrib.get(
            "{http://justice.gc.ca/lims}inforce-start-date", None
        ),
        "last_amended_date": preamble.attrib.get(
            "{http://justice.gc.ca/lims}lastAmendedDate", None
        ),
        "subsections": [
            {
                "id": i,
                "text": _get_joined_text(provision),
                "headings": get_headings(provision),
                "marginal_note": None,
                "in_force_start_date": provision.attrib.get(
                    "{http://justice.gc.ca/lims}inforce-start-date", None
                ),
                "last_amended_date": provision.attrib.get(
                    "{http://justice.gc.ca/lims}lastAmendedDate", None
                ),
                "internal_refs": get_internal_xrefs(provision),
                "external_refs": get_external_xrefs(provision),
                "lims_id": provision.attrib.get("{http://justice.gc.ca/lims}id", None),
            }
            for i, provision in enumerate(preamble.findall(".//Provision"))
        ],
        "internal_refs": get_internal_xrefs(preamble),
        "external_refs": get_external_xrefs(preamble),
        "lims_id": preamble.attrib.get("{http://justice.gc.ca/lims}id", None),
    }]


def get_schedule(schedule):
    # if schedule "id" attribute is RelatedProvs or NifProvs, skip it
    if schedule.attrib.get("id", None) in ["RelatedProvs", "NifProvs"]:
        return None
    return {
        "id": _get_text(schedule.find(".//Label")),
        # "headings": get_headings(schedule),
        "marginal_note": _get_text(schedule.find(".//MarginalNote")),
        "text": _get_joined_text(schedule),
        "in_force_start_date": schedule.attrib.get(
            "{http://justice.gc.ca/lims}inforce-start-date", None
        ),
        "last_amended_date": schedule.attrib.get(
            "{http://justice.gc.ca/lims}lastAmendedDate", None
        ),
        "subsections": [],
        "internal_refs": get_internal_xrefs(schedule),
        "external_refs": get_external_xrefs(schedule),
        "originating_ref": _get_text(schedule.find(".//OriginatingRef")),
        "lims_id": schedule.attrib.get("{http://justice.gc.ca/lims}id", None),
    }


def get_headings(element):
    """
    Headings are found in the inner text of <Heading> tags.
    Returns an array of headings, i.e. ["HeadingLevel1", "HeadingLevel2", "HeadingLevel3"]
    In each case (level 1, 2, 3), the returned heading is always the one CLOSEST (i.e. above) the element
    Note that headings are NOT correctly nested in the hierarchy
    They may be siblings to the element etc. We cannot rely on xpath
    """
    # Brute force solution: Traverse document from top to bottom, keeping track of headings until we hit the element
    headings = [None, None, None, None, None, None]  # 6 levels of headings
    root = element.getroottree().getroot()
    for e in root.iter():
        if e.tag == "Heading":
            level = int(e.attrib.get("level", 1))
            headings[level - 1] = _get_joined_text(e)
            # Remove formatting (e.g. bold) from headings
            headings[level - 1] = (
                headings[level - 1].replace("**", "").replace("__", "")
            )
            for i in range(level, 6):
                headings[i] = None
        if e == element:
            break
    return [h for h in headings if h is not None]