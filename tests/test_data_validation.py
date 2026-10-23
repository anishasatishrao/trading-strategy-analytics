import pandas as pd

from src.validate_data import validate_dataframe


def base_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "Symbol": ["TEST", "TEST", "TEST"],
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [104.0, 105.0, 106.0],
            "Adj_Close": [104.0, 105.0, 106.0],
            "Volume": [1000, 1100, 1200],
        }
    )


def test_valid_data_passes_cleanly():
    df = base_df()
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert len(clean) == 3
    assert len(rejected) == 0
    assert report["valid_rows"] == 3
    assert report["rejected_rows"] == 0


def test_duplicate_symbol_date_is_rejected():
    df = base_df()
    dup_row = df.iloc[[0]].copy()
    df = pd.concat([df, dup_row], ignore_index=True)
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert report["duplicate_count"] == 1
    assert len(clean) == 3
    assert len(rejected) == 1


def test_invalid_negative_price_is_rejected():
    df = base_df()
    df.loc[1, "Close"] = -5.0
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert report["count_invalid_price"] == 1
    assert len(clean) == 2
    assert "2024-01-02" not in clean["Date"].astype(str).values


def test_missing_required_columns_raises_fatal_error():
    df = base_df().drop(columns=["Volume"])
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert "fatal_error" in report
    assert len(clean) == 0


def test_unparseable_date_is_rejected():
    df = base_df()
    df.loc[0, "Date"] = "not-a-date"
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert report["count_null_date"] == 1
    assert len(clean) == 2


def test_high_lower_than_low_is_rejected():
    df = base_df()
    df.loc[0, "High"] = 90.0  # High < Low -> invalid
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert report["count_high_lower_than_low"] == 1
    assert len(clean) == 2


def test_negative_volume_is_rejected():
    df = base_df()
    df.loc[0, "Volume"] = -100
    clean, rejected, report = validate_dataframe(df, "TEST")
    assert report["count_negative_volume"] == 1
    assert len(clean) == 2
