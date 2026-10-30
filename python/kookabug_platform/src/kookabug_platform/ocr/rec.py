# 이 파일은 RapidOCR v3.10.0(`rapidocr/ch_ppocr_rec/main.py`·`utils.py`, Copyright (c) 2021
# RapidOCR Authors, 그 바탕은 Copyright (c) 2020 PaddlePaddle Authors)를 옮겨 고친 것이다. 원본과
# 같이 Apache License 2.0을 따른다 (`NOTICE` 참고).
# 바꾼 점: 낱말 상자·RTL 처리를 빼고, 묶음마다 추론을 따로 불러 그 사이에 기한을 볼 수 있게 했다.
"""문자 인식: 줄 이미지 → 높이 48 정규화 → CTC 탐욕 디코드."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

import cv2
import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ["BATCH", "IMG_H", "IMG_W", "CtcDecoder", "batches", "rec_input"]

IMG_H: Final = 48
IMG_W: Final = 320
BATCH: Final = 6


def batches(crops: Sequence[NDArray[np.uint8]]) -> list[list[int]]:
    """너비/높이 비가 비슷한 것끼리 `BATCH`개씩 묶는다 (채움을 줄여 빨라진다). 원래 순서 번호."""
    order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / crops[i].shape[0])
    return [order[i : i + BATCH] for i in range(0, len(order), BATCH)]


def rec_input(crops: Sequence[NDArray[np.uint8]]) -> NDArray[np.float32]:
    """한 묶음의 인식 모델 입력 (N, 3, 48, W). W는 묶음 안 가장 긴 비율에 맞춘다."""
    max_ratio = max([IMG_W / IMG_H, *(c.shape[1] / c.shape[0] for c in crops)])
    width = int(IMG_H * max_ratio)
    out = np.zeros((len(crops), 3, IMG_H, width), dtype=np.float32)
    for i, crop in enumerate(crops):
        h, w = crop.shape[:2]
        resized_w = min(width, math.ceil(IMG_H * w / h))
        resized = cv2.resize(crop, (resized_w, IMG_H)).astype(np.float32)
        out[i, :, :, :resized_w] = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
    return out


class CtcDecoder:
    """CTC 탐욕 디코드. 문자표 = 공백 기호(blank, 0번) + 모델 사전 + 띄어쓰기."""

    def __init__(self, characters: Sequence[str]) -> None:
        self.characters: Final = ["", *characters, " "]

    def __call__(self, preds: NDArray[np.float32]) -> list[tuple[str, float]]:
        """(N, T, C) → 줄마다 (글자, 점수). 점수는 남긴 글자 확률의 평균, 글자가 없으면 0."""
        index = preds.argmax(axis=2)
        prob = preds.max(axis=2)
        out: list[tuple[str, float]] = []
        for tokens, probs in zip(index, prob, strict=True):
            keep = np.ones(len(tokens), dtype=bool)
            keep[1:] = tokens[1:] != tokens[:-1]
            keep &= tokens != 0
            text = "".join(self.characters[t] for t in tokens[keep] if t < len(self.characters))
            score = float(np.mean(probs[keep])) if keep.any() else 0.0
            out.append((text, score))
        return out
