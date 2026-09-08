import pdfplumber
import pandas as pd
import glob
import os
import csv
import json


def extract_tables_from_pdf(filename):
    tables = []
    try:
        with pdfplumber.open(filename) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    tables.append(table)
        return tables
    except Exception as e:
        print(f"Error opening PDF file: {e}")
        return None


def save_tables_as_csv(tables, filename):
    base_filename = filename.rsplit('.', 1)[0]
    for i, table in enumerate(tables):
        header = table[0]
        data = table[1:]
        df = pd.DataFrame(data, columns=header)
        csv_filename = f"{base_filename}_table_{i+1}.csv"
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"Saved table {i+1} as {csv_filename}")


def merge_csv_files(folder_path, output_csv, pattern="*.csv", add_source_column=True):
    """
    Merge all CSVs in a folder into a single CSV.
    - pattern: glob pattern to select which CSVs to include (e.g. "*_table_*.csv")
    - add_source_column: adds a column with the originating filename, useful for tracing rows back
    """
    csv_files = sorted(glob.glob(os.path.join(folder_path, pattern)))
    if not csv_files:
        print(f"No CSV files found matching {pattern} in {folder_path}")
        return None

    dfs = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, encoding='utf-8-sig')
            if add_source_column:
                df['source_file'] = os.path.basename(f)
            dfs.append(df)
            print(f"Loaded {f} ({len(df)} rows)")
        except Exception as e:
            print(f"Skipping {f}: {e}")

    if not dfs:
        print("No CSVs could be loaded.")
        return None

    # Use concat with sort=False to preserve column order; handles mismatched columns gracefully
    merged_df = pd.concat(dfs, ignore_index=True, sort=False)
    merged_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f"Merged {len(csv_files)} files into {output_csv} ({len(merged_df)} total rows)")
    return merged_df


def csv_to_json(csvFilePath, jsonFilePath):
    jsonArray = []
    with open(csvFilePath, encoding='utf-8-sig', errors='ignore') as csvf:
        csvReader = csv.DictReader(csvf)
        for row in csvReader:
            jsonArray.append(row)
    with open(jsonFilePath, 'w', encoding='utf-8') as jsonf:
        jsonString = json.dumps(jsonArray, indent=4)
        jsonf.write(jsonString)
    print(f"Converted {csvFilePath} to {jsonFilePath}")


if __name__ == "__main__":
    extra_pdfs_folder = r"/home/vijaykumar/Desktop/project/extra_pdfs"

    # Step 1 (optional): if you still need to extract from a fresh PDF, do it here
    # filename = os.path.join(extra_pdzfs_folder, "Table.pdf")
    # tables = extract_tables_from_pdf(filename)
    # if tables:
    #     save_tables_as_csv(tables, filename)

    # Step 2: merge all the per-table CSVs already sitting in extra_pdfs
    merged_csv_path = os.path.join(extra_pdfs_folder, "merged_output.csv")
    merge_csv_files(extra_pdfs_folder, merged_csv_path, pattern="*_table_*.csv")

    # Step 3 (optional): convert the merged CSV to JSON
    merged_json_path = os.path.join(extra_pdfs_folder, "merged_output.json")
    csv_to_json(merged_csv_path, merged_json_path)

    print("Conversion completed successfully")