# pylint: disable=no-member
import os

from bitcart import BTC
from fastapi import HTTPException
from sqlalchemy.orm import relationship

from . import settings, utils
from .db import db

# shortcuts
RPC_URL = settings.RPC_URL
RPC_USER = settings.RPC_USER
RPC_PASS = settings.RPC_PASS
Column = db.Column
Integer = db.Integer
String = db.String
Boolean = db.Boolean
Numeric = db.Numeric
DateTime = db.DateTime
Text = db.Text
ForeignKey = db.ForeignKey


class User(db.Model):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    email = Column(String, index=True)
    hashed_password = Column(String)
    is_superuser = Column(Boolean(), default=False)
    token = relationship("Token", uselist=False, back_populates="users")


class Token(db.Model):
    __tablename__ = "tokens"
    key = Column(String(length=40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    user = relationship("User", back_populates="tokens")
    created = Column(DateTime(True))

    @classmethod
    async def create(cls, user: User):
        user_id = user.id
        key = os.urandom(20).hex()
        created = utils.now()
        return await super().create(user_id=user_id, key=key, created=created)


class Wallet(db.Model):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(length=1000), unique=True, index=True)
    xpub = Column(String(length=1000), unique=True, index=True)
    balance = Column(Numeric(16, 8))
    user_id = Column(Integer, ForeignKey(User.id, ondelete="SET NULL"))
    user = relationship(User, backref="wallets")


class Store(db.Model):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(1000), unique=True, index=True)
    domain = Column(String(1000), unique=True, index=True)
    template = Column(String(1000))
    email = Column(String(1000), unique=True, index=True)
    wallet_id = Column(
        ForeignKey(
            "wallets.id", deferrable=True, initially="DEFERRED", ondelete="SET NULL"
        ),
        index=True,
    )
    email_host = Column(String(1000))
    email_password = Column(String(1000))
    email_port = Column(Integer)
    email_use_ssl = Column(Boolean)
    email_user = Column(String(1000))

    wallet = relationship("Wallet")


class Product(db.Model):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Numeric(16, 8), nullable=False)
    quantity = Column(Numeric(16, 8), nullable=False)
    title = Column(String(1000), nullable=False)
    date = Column(DateTime(True), nullable=False)
    description = Column(Text)
    image = Column(String(100))
    store_id = Column(
        ForeignKey(
            "stores.id", deferrable=True, initially="DEFERRED", ondelete="SET NULL"
        ),
        index=True,
    )
    status = Column(String(1000), nullable=False)

    store = relationship("Store")


class ProductxInvoice(db.Model):
    __tablename__ = "productsxinvoices"

    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"))
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"))


from gino.crud import UpdateRequest


class MyUpdateRequest(UpdateRequest):
    def update(self, **kwargs):
        self.products = kwargs.get("products")
        if self.products:
            kwargs.pop("products")
        return super().update(**kwargs)

    async def apply(self):
        await ProductxInvoice.delete.where(
            ProductxInvoice.invoice_id == self._instance.id
        ).gino.status()
        for i in self.products:
            await ProductxInvoice.create(invoice_id=self._instance.id, product_id=i)
        self._instance.products = self.products
        return await super().apply()


class Invoice(db.Model):
    __tablename__ = "invoices"
    _update_request_cls = MyUpdateRequest

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Numeric(16, 8), nullable=False)
    status = Column(String(1000), nullable=False)
    date = Column(DateTime(True), nullable=False)
    bitcoin_address = Column(String(255), nullable=False)
    bitcoin_url = Column(String(255), nullable=False)
    products = relationship("Product", secondary=ProductxInvoice)

    @classmethod
    async def create(cls, **kwargs):
        products = kwargs["products"]
        if not products:
            raise HTTPException(422, "Products list empty")
        product = await Product.get(products[0])
        if not product:
            raise HTTPException(422, f"Product {products[0]} doesn't exist!")
        store = await Store.get(product.store_id)
        if not store:
            raise HTTPException(422, f"Store {product.store_id} doesn't exist!")
        wallet = await Wallet.get(store.wallet_id)
        if not wallet:
            raise HTTPException(422, "No wallet linked")
        xpub = wallet.xpub
        async with BTC(RPC_URL, rpc_user=RPC_USER, rpc_pass=RPC_PASS, xpub=xpub) as btc:
            data_got = await btc.addrequest(
                kwargs["amount"], description=product.description
            )
        kwargs["bitcoin_address"] = data_got["address"]
        kwargs["bitcoin_url"] = data_got["URI"]
        kwargs.pop("products")
        return await super().create(**kwargs), xpub

