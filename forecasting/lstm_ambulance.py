"""LSTM for ambulance demand: nonlinear interactions between hour, weekend,
weather and recent demand that linear seasonal models underfit.

Architecture: 2 stacked LSTM layers x 64 units, dropout 0.2, dense head.
Sequence length 168 (one week), batch 64, Adam lr=1e-3, early stopping
patience 5 on val loss. Quantile-ish intervals via residual std on val set.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from forecasting.evaluate import metrics

log = logging.getLogger(__name__)

SEQ_LEN = 168
BATCH = 64
EPOCHS = 40
PATIENCE = 5
FEATURES = ["dispatch_count", "temp_c", "precip_mm", "hour_sin", "hour_cos", "is_weekend"]


class AmbulanceLSTM(nn.Module):
    def __init__(self, n_features: int = len(FEATURES)):
        super().__init__()
        self.lstm = nn.LSTM(n_features, 64, num_layers=2, dropout=0.2, batch_first=True)
        self.head = nn.Sequential(nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def _prepare(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict]:
    d = df.sort_values("ts").copy()
    d["hour_sin"] = np.sin(2 * np.pi * d["ts"].dt.hour / 24)
    d["hour_cos"] = np.cos(2 * np.pi * d["ts"].dt.hour / 24)
    d["is_weekend"] = (d["ts"].dt.dayofweek >= 5).astype(float)
    scaler = {c: (d[c].mean(), d[c].std() or 1.0) for c in ["dispatch_count", "temp_c", "precip_mm"]}
    for c, (mu, sd) in scaler.items():
        d[c] = (d[c] - mu) / sd
    arr = d[FEATURES].to_numpy(np.float32)
    X = np.stack([arr[i : i + SEQ_LEN] for i in range(len(arr) - SEQ_LEN)])
    y = arr[SEQ_LEN:, 0]  # next-hour scaled dispatch_count
    return X, y, scaler


def train(df: pd.DataFrame) -> tuple[AmbulanceLSTM, dict, dict]:
    X, y, scaler = _prepare(df)
    split = int(len(X) * 0.85)
    train_ds = TensorDataset(torch.tensor(X[:split]), torch.tensor(y[:split]))
    val_X, val_y = torch.tensor(X[split:]), torch.tensor(y[split:])

    model = AmbulanceLSTM()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    best, patience = float("inf"), 0

    for epoch in range(EPOCHS):
        model.train()
        for xb, yb in DataLoader(train_ds, batch_size=BATCH, shuffle=True):
            opt.zero_grad()
            loss_fn(model(xb), yb).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val_loss = loss_fn(model(val_X), val_y).item()
        if val_loss < best - 1e-5:
            best, patience = val_loss, 0
            torch.save(model.state_dict(), "/tmp/lstm_best.pt")  # noqa: S108
        else:
            patience += 1
            if patience >= PATIENCE:
                log.info("early stop at epoch %d (val=%.5f)", epoch, best)
                break

    model.load_state_dict(torch.load("/tmp/lstm_best.pt"))  # noqa: S108
    mu, sd = scaler["dispatch_count"]
    with torch.no_grad():
        pred = model(val_X).numpy() * sd + mu
    actual = val_y.numpy() * sd + mu
    resid_sd = float(np.std(actual - pred))
    m = metrics(actual, pred, pred - 1.645 * resid_sd, pred + 1.645 * resid_sd)
    log.info("lstm_ambulance holdout: %s", m)
    return model, m, {"scaler": scaler, "resid_sd": resid_sd}
