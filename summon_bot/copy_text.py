"""Player-facing HTML. Dynamic values are escaped by callers."""

from __future__ import annotations

HELP_HOME = """<b>Summon</b>
Characters appear in groups. Type the exact name to catch them.

<b>Play</b>
/collection /daily /spin /shop /quests /profile /streak /top

<b>Trade</b>
/market /sell /auction /bid /gift /pay /vault /premium

<b>Lookup</b>
/check /search /fav /nguess /hmode /font /stats

Open Help for the staff list. Group replies to /balance, /profile, and /collection are ephemeral: only you and the bot see them."""

HELP_PLAY = """<b>Catching</b>
After enough chat messages a portrait appears. Reply with the name. /claimlist shows the timer. The hint button spends coins and is shown only to you.

<b>Album</b>
/collection walks your cards. /hmode filters by rarity. /fav marks the open card. /profile draws your card.

<b>Coins</b>
/daily keeps a streak. /spin uses a dice. /quests pays three small goals each UTC day."""

HELP_TRADE = """<b>Market</b>
/sell &lt;card id&gt; &lt;price&gt; lists a card. /market browses listings. Prices accept 1500, 15k, or 2m.

<b>Auctions</b>
/auction &lt;card id&gt; &lt;start&gt; [hours] escrows bids. /bid &lt;auction id&gt; &lt;amount&gt; refunds the previous bidder.

<b>Stars</b>
/premium is a Telegram Stars invoice (XTR). /vault sends paid media; the card is granted only after purchase. /refund is owner-only."""

HELP_STAFF = """<b>Sudo</b>
/spawn /checkspawn /changetime /chance /chancelist
/ban /unban /warn /addchar /updatechar /delete
/givemoney /sudolist

<b>Owner</b>
/owner /addsudo /rmsudo /gencode /broadcast /removeall /transfer /stars /sublink /restart

/addchar replies to a photo: Name | Series | Rarity | optional alias.
Button colors, ephemeral commands, rich help, reactions, Stars, paid media, and guest replies use the current Bot API."""


def home_text(name: str) -> str:
    from .richfmt import welcome_html

    return welcome_html(name, HELP_HOME)
