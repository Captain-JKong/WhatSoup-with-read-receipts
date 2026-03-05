from bs4 import BeautifulSoup

with open('right-panel.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f, 'lxml')

# Find a message row
msg = soup.find('div', class_='focusable-list-item')
if msg:
    print("Found message. Walking up parent tree:")
    node = msg
    depth = 0
    while node and depth < 6:
        if node.name:
            attrs = []
            if node.name == 'div':
                attrs = [(k, v) for k, v in node.attrs.items() if k in ['id', 'role', 'class', 'data-tab']]
            attrs_str = ' '.join(f'{k}="{str(v)[:60]}"' for k, v in attrs)
            indent = '  ' * depth
            print(f"{indent}{node.name} {attrs_str}")
        node = node.parent
        depth += 1
else:
    print("No focusable-list-item found")
