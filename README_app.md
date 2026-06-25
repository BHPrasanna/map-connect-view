# Modbus Mapping Studio (PyQt5)

A clean desktop GUI for mapping Modbus parameters from a CSV and monitoring live values.

## Install

```bash
pip install PyQt5 pymodbus
```

`pymodbus` is optional — without it the app runs in **simulated** mode (random values) so you can still try the full workflow.

## Run

```bash
python app.py
```

## Workflow

1. **Mapping tab** (default) — click **Import CSV** to load parameters, or **+ Add Parameter** to map one manually.
2. After import, the app auto-switches to the **Connection** tab.
3. Pick **Modbus TCP**, fill IP / Port / Unit ID, then **Connect**. If no mapping exists, you'll be prompted to import a CSV first.
4. **Parameters** tab shows names + addresses immediately after mapping, and the **Value** column fills in once connected.

## CSV format

Columns (case-insensitive, order-independent):

| address | parameter | data_type | scaling | unit |
|---------|-----------|-----------|---------|------|
| 40001   | Voltage L1 | u16      | 0.1     | V    |

A sample is provided in `sample_parameters.csv`.
