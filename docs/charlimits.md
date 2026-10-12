# Character limits explained

## Why are character limits needed?
Character limits are used to stop what is known as a text buffer overflow. If ORAS did not have character limits, there could potentially be scenarios where the lack of a string limit could be exploited and allow access into areas of the console that were not intentionally meant to be accessed ([Basehaxx](https://mrnbayoh.github.io/basehaxx/) is a great example of this). 
Since ORAS appears to hardcode the character limits in for Pokémon names, trainer names/classes and place names (at least I have not found a way to bypass this), the best solution has been to place character limits in specific sections of the extracted text files.

## How do you know what sections to limit?
PK3DS exports the text of both the game and story in a format where it is split through 'Text File' headers.
![alt text](https://i.ibb.co/SD6dGYwP/example.png "Text File example") 

Through a bit of experimentation including *many* crashes and cross-referencing text from the original story and game of Alpha Sapphire, I've been able to pick out the sections that require limiting due to potential crashes from overflow:

###### *Note: for easier writing and understanding, 'Text File' has been replaced with 'Section'. They both mean the same thing, though.*
* **Section 0 - Location descriptors**(? requires some more clarity), capped to 16 characters.
* **Section 5 - Alternate Pokémon forms** (megas, weather and locational forms etc.), limited to 20 characters as although these should only apply to Dex entries, better to be safe than sorry.
*  **Sections 14 & 15 - Moves**, capped to 16 characters as this can cause crashes very easily *(as I've painstakingly learned..)*
* **Section 18 - Pokémon typings**, capped to 12 characters.
* **Section 21 - Trainer classes**, capped to 16 characters.
* **Sections 22, 153 - 154 - Trainer names**, capped to 16 characters. This realistically shouldn't need more characters but probably could accept more. More testing required.
* **Section 37 - Pokémon abilities**, capped to 16 characters.
* **Section 51 - Pokémon natures**, capped to 12 characters.
* **Section 90 - Location names**, capped to 16 characters. This would cause a lot of crashes in testing, a special thanks to 'The secret headquarters of the Flare team.'...
* **Section 98 - Pokémon species names**, capped to 12 characters. 12 was found to be the safe limit in testing, turns out a Treecko named 'clearance vehicles' was not valid enough for Alpha Sapphire during testing.
* **Sections 113 - 116 - Items and their plurals**, capped to 16 characters each (ignoring variables). Appears to be used also to display the item in bag or text. 
