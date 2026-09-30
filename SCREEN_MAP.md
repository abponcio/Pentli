# Screen and state map

| Image | Surface | State |
| --- | --- | --- |
| `01-live-rescue.png` | Operations | Driver confirmed; route, checks and activity |
| `02-donor-chat.png` | Donor | Shared surplus; pickup confirmation |
| `03-recipient-flow.png` | Recipient | Offer; accepted; received |
| `04-replanning.png` | Operations | Decline and revised offers pending |
| `05-impact.png` | Operations | Completed handovers and impact |
| `06-arabic-rtl.png` | Donor + recipient | Arabic right-to-left variants |
| `07-intake-clarification.png` | Donor | Empty intake; missing preparation time |
| `08-recipient-exceptions.png` | Recipient | Declined; expired; confirm receipt |
| `09-awaiting-offers.png` | Operations | Matching, waiting and illustrative QR |
| `10-dispatch-blocked.png` | Operations | Safety gate rejects route |
| `11-driver-handover.png` | Detail views | Simulated driver message; handover record |

## Canonical demo content

Rescue `PL-1042`: 50 chicken-biryani portions from HelloChef kitchen, prepared at 18:00, stored at room temperature, containing cashews. The first proposed split is Community kitchen 25, Family shelter 20, Community fridge 5. A nut-free care home is excluded. Family shelter declines; the revised proposal is Community kitchen 30 and Community fridge 20. Revised offers must be accepted before dispatch. Example van: `HelloChef van 03`; example pickup 19:52; example ETAs 20:18 and 20:31. Example receipt times are 20:20 and 20:33. In the live build, one seeded clock must make these events consistent.

The 22:00 deadline is illustrative and always marked **Demo rule**. Real deadline calculation and dispatch safety must use approved rules and actual inputs. All organisations, positions, messages and QR graphics in the images are demo content. Real WhatsApp, logins, forecasting and Iftar mode are outside this reference scope.

Generated with OpenAI's built-in image-generation tool as UI mockups. The first operations board established the Plentli visual system and was used as a style reference for the other boards. These PNGs are reference images, not implemented or validated application screens.
