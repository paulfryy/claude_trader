"""
Trading universe — the full set of symbols we scan for opportunities.
S&P 500 components + major ETFs.
"""

# S&P 500 components (as of April 2026, 503 tickers)
SP500 = [
    "A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM",
    "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM",
    "ALB", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP",
    "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH", "APO", "APP",
    "APTV", "ARE", "ARES", "ATO", "AVB", "AVGO", "AVY", "AWK", "AXON", "AXP",
    "AZO", "BA", "BAC", "BALL", "BAX", "BBY", "BDX", "BEN", "BG",
    "BIIB", "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY", "BR", "BRO",
    "BSX", "BX", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE",
    "CBRE", "CCI", "CCL", "CDNS", "CDW", "CEG", "CF", "CFG", "CHD", "CHRW",
    "CHTR", "CI", "CIEN", "CINF", "CL", "CLX", "CMCSA", "CME", "CMG", "CMI",
    "CMS", "CNC", "CNP", "COF", "COHR", "COIN", "COO", "COP", "COR", "COST",
    "CPAY", "CPB", "CPRT", "CPT", "CRH", "CRL", "CRM", "CRWD", "CSCO", "CSGP",
    "CSX", "CTAS", "CTRA", "CTSH", "CTVA", "CVNA", "CVS", "CVX", "D", "DAL",
    "DASH", "DD", "DDOG", "DE", "DECK", "DELL", "DG", "DGX", "DHI", "DHR",
    "DIS", "DLR", "DLTR", "DOC", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK",
    "DVA", "DVN", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EG", "EIX",
    "EL", "ELV", "EME", "EMR", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE",
    "ES", "ESS", "ETN", "ETR", "EVRG", "EW", "EXC", "EXE", "EXPD", "EXPE",
    "EXR", "F", "FANG", "FAST", "FCX", "FDS", "FDX", "FE", "FFIV", "FICO",
    "FIS", "FISV", "FITB", "FIX", "FOX", "FOXA", "FRT", "FSLR", "FTNT", "FTV",
    "GD", "GDDY", "GE", "GEHC", "GEN", "GEV", "GILD", "GIS", "GL", "GLW",
    "GM", "GNRC", "GOOG", "GOOGL", "GPC", "GPN", "GRMN", "GS", "GWW", "HAL",
    "HAS", "HBAN", "HCA", "HD", "HIG", "HII", "HLT", "HOLX", "HON", "HOOD",
    "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUBB", "HUM", "HWM", "IBKR",
    "IBM", "ICE", "IDXX", "IEX", "IFF", "INCY", "INTC", "INTU", "INVH", "IP",
    "IQV", "IR", "IRM", "ISRG", "IT", "ITW", "IVZ", "J", "JBHT", "JBL",
    "JCI", "JKHY", "JNJ", "JPM", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR",
    "KLAC", "KMB", "KMI", "KO", "KR", "KVUE", "L", "LDOS", "LEN", "LH",
    "LHX", "LII", "LIN", "LITE", "LLY", "LMT", "LNT", "LOW", "LRCX", "LULU",
    "LUV", "LVS", "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP",
    "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MGM", "MKC", "MLM", "MMM",
    "MNST", "MO", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MS", "MSCI",
    "MSFT", "MSI", "MTB", "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE", "NEM",
    "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE",
    "NVDA", "NVR", "NWS", "NWSA", "NXPI", "O", "ODFL", "OKE", "OMC", "ON",
    "ORCL", "ORLY", "OTIS", "OXY", "PANW", "PAYX", "PCAR", "PCG", "PEG", "PEP",
    "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM",
    "PNC", "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA",
    "PSX", "PTC", "PWR", "PYPL", "QCOM", "RCL", "REG", "REGN", "RF",
    "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "RVTY",
    "SBAC", "SBUX", "SCHW", "SHW", "SJM", "SLB", "SMCI", "SNA",
    "SNPS", "SO", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD", "STT", "STX",
    "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG",
    "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO", "TMO", "TMUS",
    "TPL", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT",
    "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR", "UHS", "ULTA",
    "UNH", "UNP", "UPS", "URI", "USB", "V", "VICI", "VLO", "VLTO", "VMC",
    "VRSK", "VRSN", "VRT", "VRTX", "VST", "VTR", "VTRS", "VZ", "WAB", "WAT",
    "WBD", "WDAY", "WDC", "WEC", "WELL", "WFC", "WM", "WMB", "WMT", "WRB",
    "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL", "YUM",
    "ZBH", "ZBRA", "ZTS",
]

# Major ETFs for sector/thematic coverage
MAJOR_ETFS = [
    "ARKK",   # ARK Innovation
    "DIA",    # Dow Jones Industrial Average
    "EEM",    # Emerging Markets
    "GLD",    # Gold
    "HYG",    # High Yield Corporate Bond
    "IBB",    # Biotech
    "IWM",    # Russell 2000
    "QQQ",    # Nasdaq 100
    "SLV",    # Silver
    "SMH",    # Semiconductors (VanEck)
    "SOXX",   # Semiconductors (iShares)
    "SPY",    # S&P 500
    "TLT",    # 20+ Year Treasury Bond
    "USO",    # US Oil
    "VTI",    # Total Stock Market
    "VOO",    # S&P 500 (Vanguard)
    "VWO",    # Emerging Markets (Vanguard)
    "XBI",    # Biotech (SPDR)
    "XLB",    # Materials
    "XLC",    # Communication Services
    "XLE",    # Energy
    "XLF",    # Financials
    "XLI",    # Industrials
    "XLK",    # Technology
    "XLP",    # Consumer Staples
    "XLRE",   # Real Estate
    "XLU",    # Utilities
    "XLV",    # Health Care
    "XLY",    # Consumer Discretionary
    "XME",    # Metals & Mining
]

# Sector classification — used for concentration limits.
# This is a coarse mapping; covers most common tickers we trade.
# Unknown symbols fall into "other" and are lenient (no concentration limit).
SECTOR_MAP = {
    # Technology (GICS: Information Technology — hardware, software, semiconductors)
    # Note: AMZN/TSLA = Consumer Discretionary, GOOGL/META/NFLX = Communications per GICS
    "AAPL": "technology", "MSFT": "technology", "NVDA": "technology",
    "AMD": "technology", "INTC": "technology", "ORCL": "technology", "CRM": "technology",
    "ADBE": "technology", "AVGO": "technology", "QCOM": "technology",
    "CSCO": "technology", "IBM": "technology", "TXN": "technology", "MU": "technology",
    "SMCI": "technology", "PLTR": "technology", "CRWD": "technology", "PANW": "technology",
    "NOW": "technology", "SNOW": "technology", "DELL": "technology", "HPE": "technology",
    "HPQ": "technology", "GLW": "technology", "KLAC": "technology", "LRCX": "technology",
    "AMAT": "technology", "ANET": "technology", "CDNS": "technology", "SNPS": "technology",
    "FTNT": "technology", "ADI": "technology", "ADSK": "technology", "MCHP": "technology",
    "MRVL": "technology", "INTU": "technology", "WDAY": "technology", "CTSH": "technology",
    "APH": "technology", "ON": "technology", "NXPI": "technology", "MPWR": "technology",
    "XLK": "technology", "SMH": "technology", "SOXX": "technology",

    # Financials
    "JPM": "financial", "BAC": "financial", "WFC": "financial", "C": "financial",
    "GS": "financial", "MS": "financial", "USB": "financial", "PNC": "financial",
    "TFC": "financial", "FITB": "financial", "RF": "financial", "KEY": "financial",
    "HBAN": "financial", "CFG": "financial", "BLK": "financial", "SCHW": "financial",
    "AXP": "financial", "V": "financial", "MA": "financial", "PYPL": "financial",
    "BK": "financial", "STT": "financial", "NTRS": "financial", "MTB": "financial",
    "COF": "financial", "SYF": "financial", "IBKR": "financial", "HOOD": "financial",
    "XLF": "financial", "KRE": "financial", "KBE": "financial",

    # Energy
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "EOG": "energy", "MPC": "energy", "PSX": "energy", "VLO": "energy",
    "OXY": "energy", "HAL": "energy", "BKR": "energy", "DVN": "energy",
    "FANG": "energy", "APA": "energy", "EQT": "energy", "TRGP": "energy",
    "XLE": "energy", "USO": "energy", "OIH": "energy",

    # Healthcare
    "JNJ": "healthcare", "UNH": "healthcare", "LLY": "healthcare", "PFE": "healthcare",
    "MRK": "healthcare", "ABBV": "healthcare", "TMO": "healthcare", "ABT": "healthcare",
    "DHR": "healthcare", "BMY": "healthcare", "AMGN": "healthcare", "CVS": "healthcare",
    "MDT": "healthcare", "GILD": "healthcare", "ISRG": "healthcare", "CI": "healthcare",
    "ELV": "healthcare", "REGN": "healthcare", "VRTX": "healthcare", "HUM": "healthcare",
    "BSX": "healthcare", "SYK": "healthcare", "BDX": "healthcare", "ZTS": "healthcare",
    "MRNA": "healthcare", "BIIB": "healthcare", "DXCM": "healthcare", "EW": "healthcare",
    "IDXX": "healthcare", "IQV": "healthcare", "A": "healthcare", "RMD": "healthcare",
    "HCA": "healthcare", "MCK": "healthcare", "COR": "healthcare", "CNC": "healthcare",
    "XLV": "healthcare", "IBB": "healthcare", "XBI": "healthcare",

    # Consumer Discretionary (GICS)
    "AMZN": "consumer_disc", "TSLA": "consumer_disc",
    "HD": "consumer_disc", "MCD": "consumer_disc", "NKE": "consumer_disc",
    "LOW": "consumer_disc", "SBUX": "consumer_disc", "TJX": "consumer_disc",
    "BKNG": "consumer_disc", "ABNB": "consumer_disc", "MAR": "consumer_disc",
    "HLT": "consumer_disc", "GM": "consumer_disc", "F": "consumer_disc",
    "CMG": "consumer_disc", "ORLY": "consumer_disc", "AZO": "consumer_disc",
    "ROST": "consumer_disc", "ULTA": "consumer_disc", "DECK": "consumer_disc",
    "LULU": "consumer_disc", "YUM": "consumer_disc", "DPZ": "consumer_disc",
    "DHI": "consumer_disc", "LEN": "consumer_disc", "PHM": "consumer_disc",
    "NVR": "consumer_disc", "XLY": "consumer_disc",

    # Consumer Staples
    "PG": "consumer_staples", "KO": "consumer_staples", "PEP": "consumer_staples",
    "WMT": "consumer_staples", "COST": "consumer_staples", "PM": "consumer_staples",
    "MO": "consumer_staples", "CL": "consumer_staples", "MDLZ": "consumer_staples",
    "KMB": "consumer_staples", "GIS": "consumer_staples", "K": "consumer_staples",
    "HRL": "consumer_staples", "KHC": "consumer_staples", "STZ": "consumer_staples",
    "KDP": "consumer_staples", "MNST": "consumer_staples", "CLX": "consumer_staples",
    "CHD": "consumer_staples", "SYY": "consumer_staples", "TGT": "consumer_staples",
    "DG": "consumer_staples", "DLTR": "consumer_staples", "KR": "consumer_staples",
    "XLP": "consumer_staples",

    # Industrials
    "BA": "industrial", "CAT": "industrial", "GE": "industrial", "HON": "industrial",
    "UPS": "industrial", "RTX": "industrial", "LMT": "industrial", "NOC": "industrial",
    "GD": "industrial", "DE": "industrial", "FDX": "industrial", "UNP": "industrial",
    "CSX": "industrial", "NSC": "industrial", "MMM": "industrial", "ETN": "industrial",
    "EMR": "industrial", "ITW": "industrial", "PH": "industrial", "CMI": "industrial",
    "ROK": "industrial", "JCI": "industrial", "CARR": "industrial", "OTIS": "industrial",
    "PCAR": "industrial", "URI": "industrial", "GNRC": "industrial", "LUV": "industrial",
    "DAL": "industrial", "UAL": "industrial", "AAL": "industrial", "XLI": "industrial",

    # Materials
    "LIN": "materials", "APD": "materials", "SHW": "materials", "ECL": "materials",
    "FCX": "materials", "NEM": "materials", "DD": "materials", "DOW": "materials",
    "PPG": "materials", "CTVA": "materials", "NUE": "materials", "STLD": "materials",
    "VMC": "materials", "MLM": "materials", "ALB": "materials", "IFF": "materials",
    "MOS": "materials", "CF": "materials", "XLB": "materials", "GLD": "materials",
    "SLV": "materials",

    # Real Estate
    "AMT": "real_estate", "PLD": "real_estate", "EQIX": "real_estate", "CCI": "real_estate",
    "PSA": "real_estate", "O": "real_estate", "SPG": "real_estate", "WELL": "real_estate",
    "DLR": "real_estate", "VICI": "real_estate", "AVB": "real_estate", "EQR": "real_estate",
    "HST": "real_estate", "XLRE": "real_estate",

    # Communications / Media (GICS: Communication Services)
    # Includes FAANG-adjacent: GOOGL, GOOG, META, NFLX all live here, not tech
    "GOOGL": "communications", "GOOG": "communications",
    "META": "communications", "NFLX": "communications",
    "T": "communications", "VZ": "communications", "TMUS": "communications",
    "CMCSA": "communications", "DIS": "communications", "WBD": "communications",
    "CHTR": "communications", "EA": "communications", "TTWO": "communications",
    "XLC": "communications",

    # Utilities
    "NEE": "utilities", "SO": "utilities", "DUK": "utilities", "D": "utilities",
    "AEP": "utilities", "SRE": "utilities", "EXC": "utilities", "XEL": "utilities",
    "WEC": "utilities", "ED": "utilities", "ETR": "utilities", "ES": "utilities",
    "XLU": "utilities",

    # Broad market / bonds / international
    "SPY": "broad_market", "QQQ": "broad_market", "IWM": "broad_market",
    "DIA": "broad_market", "VTI": "broad_market", "VOO": "broad_market",
    "TLT": "bonds", "HYG": "bonds", "LQD": "bonds", "IEF": "bonds",
    "EEM": "international", "VWO": "international", "EFA": "international",
    "ARKK": "broad_market",
}


def get_sector(symbol: str) -> str:
    """Get the sector for a symbol, or 'other' if unknown."""
    return SECTOR_MAP.get(symbol.upper(), "other")


# Anchor symbols — always included in Claude's analysis regardless of screening
ANCHOR_SYMBOLS = ["SPY", "QQQ", "IWM"]

# Full universe to scan
UNIVERSE = sorted(set(SP500 + MAJOR_ETFS))


def get_universe() -> list[str]:
    """Return the full trading universe."""
    return UNIVERSE.copy()


def get_anchor_symbols() -> list[str]:
    """Return symbols that should always be analyzed."""
    return ANCHOR_SYMBOLS.copy()
