import requests
import base64
import subprocess

url = input("Enter a URL: ").strip()
if not url.startswith("http"):
    url = "https://" + url

html = requests.get(url).text
soup = BeautifulSoup(html, "html.parser")
text = soup.body.get_text(separator="\n", strip=True)

# copy to clipboard (Windows built-in)
subprocess.run("clip", text=True, input=text)

print("Body text copied to clipboard.")
