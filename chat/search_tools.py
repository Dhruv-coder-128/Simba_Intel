import requests


def web_search(query):

    url = "https://api.duckduckgo.com/"

    params = {
        "q": query,
        "format": "json",
        "no_redirect": 1,
        "skip_disambig": 1
    }

    try:

        response = requests.get(url, params=params, timeout=10)

        data = response.json()

        results = []

        # main result
        if data.get("AbstractText"):

            results.append({
                "title": data.get("Heading", "Result"),
                "link": data.get("AbstractURL", ""),
                "snippet": data.get("AbstractText", "")
            })

        # related results
        for topic in data.get("RelatedTopics", [])[:5]:

            if isinstance(topic, dict) and topic.get("Text"):

                results.append({
                    "title": topic.get("Text"),
                    "link": topic.get("FirstURL"),
                    "snippet": topic.get("Text")
                })

        return results

    except Exception as e:

        print("SEARCH ERROR:", e)

        return []