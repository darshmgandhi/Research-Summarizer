import requests
import urllib.request as urllib

ipify_url = 'https://api.ipify.org'

try:

    response = requests.get(ipify_url)
    public_ip = response.text
    print(f"My public IP address is: {public_ip}")
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")


scholar_url = 'https://scholar.google.com/scholar?hl=en&as_sdt=0%2C40&q=author%3AYejin+author%3AChoi&btnG='

print("\nAccessing internet through TOR proxy...")
import socks
import socket
socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", 9050)
socket.socket = socks.socksocket
print(f"My public IP address is: {urllib.urlopen(ipify_url).read().decode('utf-8')}")
print(urllib.urlopen(scholar_url).read())

# proxy_support = urllib.ProxyHandler({"http" : "127.0.0.1:8118"})
# opener = urllib.build_opener(proxy_support) 
# urllib.install_opener(opener)
# opener.addheaders = [('User-agent', 'Mozilla/5.0')]
# response = opener.open(ipify_url)
# public_ip = response.read().decode('utf-8')
# print(f"My public IP address is: {public_ip}")