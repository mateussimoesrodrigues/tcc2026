from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Display(TimestampMixin, Base):
    """Etiqueta eletronica de prateleira (display fisico -- ESP32/ESP8266 +
    e-paper/OLED, ver `docs/displays-fisicos.md`) vinculada a um produto.

    Autenticacao do dispositivo e por `token` (segredo opaco gravado no
    firmware na hora de configurar o display), nao por login de
    funcionario -- ve `core/security.get_display_by_token`. Nao usamos o
    MAC/chip-id como identidade primaria porque o funcionario cria o
    registro (e recebe o token pra gravar no firmware) antes de o display
    estar necessariamente ligado; `mac_reportado` e so telemetria
    informativa, preenchida no primeiro sync.
    """

    __tablename__ = "display"

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto.id"), nullable=True)

    nome: Mapped[str] = mapped_column(String(80), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Telemetria reportada pelo proprio dispositivo a cada sincronizacao
    # (POST /displays/sincronizar) -- tudo opcional pois so existe depois
    # do primeiro contato real do hardware.
    mac_reportado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bateria_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rssi_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ultima_sincronizacao_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    produto: Mapped["Produto"] = relationship(back_populates="displays")
