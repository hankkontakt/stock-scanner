f=open('web/streamlit_app.py','r',encoding='utf-8')
c=f.read()
f.close()
i=c.find('render_stock_detail')
cnt=0
while i>=0:
    cnt+=1
    start=max(0,i-100)
    end=min(len(c),i+250)
    print(f"\n=== Occurrence #{cnt} at pos {i} ===")
    print(c[start:end])
    i=c.find('render_stock_detail',i+1)