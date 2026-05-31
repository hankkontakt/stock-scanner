import yfinance as yf
import pandas as pd

def convert_prices_to_sek(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Tar in en DataFrame med aktiepriser (där kolumnnamnen är tickers)
    och konverterar alla utländska priser till SEK baserat på historiska växelkurser.
    """
    print("💱 Konverterar historiska priser till SEK...")
    
    # 1. Definiera vilka valutapar vi behöver baserat på ditt universum
    fx_mapping = {
        'USD': 'USDSEK=X',
        'EUR': 'EURSEK=X',
        'NOK': 'NOKSEK=X',
        'DKK': 'DKKSEK=X',
        'GBP': 'GBPSEK=X'
    }
    
    # 2. Hämta valutadata för samma tidsperiod som aktiedatan
    start_date = prices_df.index.min()
    end_date = prices_df.index.max()
    
    fx_tickers = list(fx_mapping.values())
    fx_data = yf.download(fx_tickers, start=start_date, end=end_date, progress=False, auto_adjust=True)
    
    # Om yfinance returnerar MultiIndex, ta bara "Close"
    if isinstance(fx_data.columns, pd.MultiIndex):
        fx_data = fx_data['Close']
    elif isinstance(fx_data, pd.Series): # Om det bara blev ett valutapar
        fx_data = fx_data.to_frame(name=fx_tickers[0])

    # 3. Synka datumen (valutamarknaden har ibland andra helgdagar än börsen)
    # Fyll i saknade värden med föregående dags kurs — men BEGRÄNSAT till 5 dagar.
    # Obegränsad ffill().bfill() propagerade tidigare gamla kurser över långa
    # luckor och gav FX-priser som var 100x för stora (känd bugg, se CLAUDE.md).
    fx_data = fx_data.reindex(prices_df.index).ffill(limit=5).bfill(limit=5)
    
    converted_prices = prices_df.copy()
    
    # 4. Loopa igenom alla dina 535 aktier och applicera rätt valuta
    for ticker in converted_prices.columns:
        if ticker.endswith('.ST'):
            continue  # Redan i SEK, gör ingenting
            
        # Europa (Euro)
        elif ticker.endswith(('.DE', '.PA', '.AS', '.MI', '.MC', '.HE')):
            fx_pair = 'EURSEK=X'
        # Norge
        elif ticker.endswith('.OL'):
            fx_pair = 'NOKSEK=X'
        # Danmark
        elif ticker.endswith('.CO'):
            fx_pair = 'DKKSEK=X'
        # Storbritannien
        elif ticker.endswith('.L'):
            fx_pair = 'GBPSEK=X'
        # USA och Asien (ADRs handlas i USD)
        else:
            fx_pair = 'USDSEK=X'
            
        # Multiplicera aktiepriset med den historiska växelkursen för varje enskild dag
        if fx_pair in fx_data.columns:
            converted_prices[ticker] = converted_prices[ticker] * fx_data[fx_pair]
            
    return converted_prices