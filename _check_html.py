import urllib.request, re
with urllib.request.urlopen('http://127.0.0.1:5000/') as f:
    html = f.read().decode('utf-8')
scripts = re.findall(r'<script src="([^"]+)"', html)
print('页面实际加载的JS文件:')
for s in scripts:
    print('  ', s)
print('\n页面里有没有updateTotalPercent:', 'updateTotalPercent' in html)
