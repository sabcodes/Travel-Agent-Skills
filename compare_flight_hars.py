"""Compare flight-shopping HARs without exporting cookies or opaque contexts."""
import argparse
import base64
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit


def framed_payloads(text):
    decoder = json.JSONDecoder()
    offset = text.find("[")
    while offset >= 0:
        frames, size = decoder.raw_decode(text[offset:])
        offset = text.find("[", offset + size)
        for frame in frames:
            if isinstance(frame, list) and len(frame) > 2 and frame[0] == "wrb.fr" and isinstance(frame[2], str):
                yield json.loads(frame[2])


def numeric(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def public_rows(payload):
    if not isinstance(payload, list) or len(payload) < 4:
        return []
    result = []
    for section in (payload[2], payload[3]):
        for group in (section[0] or []) if section else []:
            if set(group[0][1]) != {"Singapore Airlines"}:
                continue
            legs = group[0][2]
            schedule = [{"from": leg[3], "to": leg[6], "departure_date": leg[20], "departure_time": leg[8],
                         "arrival_date": leg[21], "arrival_time": leg[10], "duration_minutes": leg[11]} for leg in legs]
            price = group[1][0][1] if group[1] and len(group[1][0]) > 1 else None
            result.append({"airlines": group[0][1], "legs": schedule, "price": price if numeric(price) and price > 0 else None,
                           "price_field_type": type(price).__name__})
    return result


def public_segments(query):
    def airport_codes(value):
        if isinstance(value, str):
            return [value] if re.fullmatch(r"[A-Z]{3}", value) else []
        if isinstance(value, list):
            return [code for child in value for code in airport_codes(child)]
        return []
    return [{"date": segment[6], "airlines": segment[4], "airports": airport_codes(segment)} for segment in query[1][13]]


def request_query(entry):
    post = entry["request"].get("postData", {})
    form = {item["name"]: [item.get("value", "")] for item in post.get("params", [])}
    form.update(parse_qs(post.get("text", "")))
    if "f.req" not in form:
        return None
    return json.loads(json.loads(form["f.req"][0])[1])


def read_capture(path):
    source = json.loads(Path(path).read_text())
    entries = source["log"]["entries"]
    internal = []
    public = {"entry_count": len(entries), "shopping": [], "missing_response_bodies": 0}
    for index, entry in enumerate(entries):
        if "FlightsFrontendService/GetShoppingResults" not in entry["request"]["url"]:
            continue
        query = request_query(entry)
        if not query:
            continue
        headers = {header["name"].lower(): header.get("value", "") for header in entry["request"].get("headers", [])}
        content = entry["response"].get("content", {})
        text = content.get("text", "")
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode()
        if not text:
            public["missing_response_bodies"] += 1
        ua = re.findall(r"(?:HeadlessChrome|Chrome|Lightpanda)/[0-9A-Za-z.+_-]+", headers.get("user-agent", ""))
        parameters = parse_qs(urlsplit(entry["request"]["url"]).query)
        observation = {"entry_index": index, "http_status": entry["response"]["status"], "response_body_present": bool(text),
                       "started_at": entry.get("startedDateTime"),
                       "segments": public_segments(query), "flags": query[2:6],
                       "request_price_reference_present": len(query) > 6 and query[6] is not None,
                       "user_agent_brands": ua, "request_header_names": sorted(headers),
                       "bot_guard_present": bool(headers.get("x-goog-batchexecute-bgr")),
                       "bot_guard_length": len(headers.get("x-goog-batchexecute-bgr", "")),
                       "build_label": parameters.get("bl", [None])[0], "language": parameters.get("hl", [None])[0],
                       "response_price_reference_present": False, "response_reference_amounts": [], "rows": []}
        for payload in framed_payloads(text) if text else []:
            observation["rows"].extend(public_rows(payload))
            if isinstance(payload, list) and len(payload) > 30 and payload[30] is not None:
                observation["response_price_reference_present"] = True
                reference = payload[30]
                if isinstance(reference, list) and reference and isinstance(reference[0], list) and len(reference[0]) > 1 and numeric(reference[0][1]):
                    observation["response_reference_amounts"].append(reference[0][1])
        public["shopping"].append(observation)
        internal.append({"query": query, "public": observation})
    unique = {(json.dumps(item["legs"], sort_keys=True), item["price"]) for row in public["shopping"] for item in row["rows"] if item["price"] is not None}
    public["unique_priced_singapore_itineraries"] = len(unique)
    return public, internal


def differences(left, right, path="$", result=None):
    result = result if result is not None else []
    if type(left) is not type(right):
        result.append({"path": path, "left_type": type(left).__name__, "right_type": type(right).__name__})
    elif isinstance(left, list):
        if len(left) != len(right):
            result.append({"path": path, "left_length": len(left), "right_length": len(right)})
        for index, (a, b) in enumerate(zip(left, right)):
            differences(a, b, f"{path}[{index}]", result)
    elif left != right:
        # Unknown values remain private; only structural locations are exported.
        result.append({"path": path, "value_differs": True})
    return result


def compare(captures):
    report = {"schema_version": 1, "captures": {}, "matching_mode_comparisons": [], "matched_itineraries": []}
    internal = {}
    for name, path in captures.items():
        report["captures"][name], internal[name] = read_capture(path)
    human = internal.get("human", [])
    for name, rows in internal.items():
        if name == "human":
            continue
        for row in rows:
            candidates = [candidate for candidate in human if candidate["public"]["flags"] == row["public"]["flags"] and
                          candidate["public"]["segments"] == row["public"]["segments"] and candidate["public"]["response_body_present"]]
            if not candidates:
                continue
            reference = candidates[-1]
            report["matching_mode_comparisons"].append({"capture": name, "human_entry": reference["public"]["entry_index"],
                "agent_entry": row["public"]["entry_index"], "flags": row["public"]["flags"],
                "main_filters_equal": reference["query"][1] == row["query"][1],
                "main_filter_differences": differences(reference["query"][1], row["query"][1]),
                "all_query_differences": differences(reference["query"], row["query"]),
                "human_request_reference_present": reference["public"]["request_price_reference_present"],
                "agent_request_reference_present": row["public"]["request_price_reference_present"],
                "human_response_reference_present": reference["public"]["response_price_reference_present"],
                "agent_response_reference_present": row["public"]["response_price_reference_present"],
                "human_bot_guard_present": reference["public"]["bot_guard_present"],
                "agent_bot_guard_present": row["public"]["bot_guard_present"],
                "human_priced_rows": sum(item["price"] is not None for item in reference["public"]["rows"]),
                "agent_priced_rows": sum(item["price"] is not None for item in row["public"]["rows"])})
        human_prices, agent_prices = {}, {}
        for candidate in human:
            for item in candidate["public"]["rows"]:
                key = json.dumps(item["legs"], sort_keys=True)
                human_prices.setdefault(key, set()).add(item["price"])
        for candidate in rows:
            for item in candidate["public"]["rows"]:
                key = json.dumps(item["legs"], sort_keys=True)
                agent_prices.setdefault(key, set()).add(item["price"])
        for key in human_prices.keys() & agent_prices.keys():
            report["matched_itineraries"].append({"capture": name, "legs": json.loads(key),
                "human_prices": sorted(human_prices[key], key=lambda value: -1 if value is None else value),
                "agent_prices": sorted(agent_prices[key], key=lambda value: -1 if value is None else value)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--human", required=True)
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--lightpanda", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = compare({"human": args.human, "chrome": args.chrome, "lightpanda": args.lightpanda})
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    for name, capture in report["captures"].items():
        print(json.dumps({"capture": name, "entries": capture["entry_count"], "shopping_updates": len(capture["shopping"]),
            "price_reference_updates": sum(row["response_price_reference_present"] for row in capture["shopping"]),
            "priced_singapore_rows": sum(item["price"] is not None for row in capture["shopping"] for item in row["rows"])}))
    print(json.dumps({"comparisons": report["matching_mode_comparisons"], "matched_itineraries": report["matched_itineraries"]}))


if __name__ == "__main__":
    main()
