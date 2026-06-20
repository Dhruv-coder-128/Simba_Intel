import requests
from bs4 import BeautifulSoup


def simba_search(query):

    url = "https://duckduckgo.com/html/"

    params = {
        "q": query
    }

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:

        response = requests.get(url, params=params, headers=headers)

        soup = BeautifulSoup(response.text, "html.parser")

        results = []

        for r in soup.select(".result__body")[:5]:

            title = r.select_one(".result__a").get_text()
            link = r.select_one(".result__a")["href"]

            snippet_tag = r.select_one(".result__snippet")
            snippet = snippet_tag.get_text() if snippet_tag else ""

            results.append({
                "title": title,
                "link": link,
                "snippet": snippet
            })

        return results

    except Exception as e:

        print("SEARCH ERROR:", e)

        return []