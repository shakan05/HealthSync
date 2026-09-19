from pathlib import Path
import pandas as pd

raw_dir = Path("data/ner/clinical_notes/raw")

# Find all .csv files in the raw folder
for file_path in raw_dir.glob("*.csv"):
    print("=" * 50)
    print(f"FILE: {file_path.name}")
    print("=" * 50)

    df = pd.read_csv(file_path)

    print("Shape:", df.shape)
    print("\nColumns:")
    print(df.columns.tolist())
    print("\nFirst rows:")
    print(df.head(3))  # Showing top 3 rows to keep output clean
    print("\nData types:")
    print(df.dtypes)
    print("\n")