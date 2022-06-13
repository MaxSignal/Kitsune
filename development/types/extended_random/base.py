import string
from datetime import datetime, timedelta
from random import Random
from .lorem import lorem_sentences

from typing import Any, List


class Extended_Random(Random):
    """
    `Random` with additional helper methods.
    """
    varchar_vocab = string.ascii_letters + string.digits
    text_vocab = string.printable
    sentence_list = lorem_sentences
    unix_epoch_start = datetime.fromtimestamp(30256871)
    max_date = None

    @classmethod
    def init(
        cls,
        seed: Any = None,
        max_date: datetime = None
    ):
        "Using the class method because python is crying about arguments."
        instance = cls(seed)

        if max_date:
            instance.max_date = max_date

        return instance

    def string(self, min_length: int = 5, max_length: int = 25, vocabulary: str = varchar_vocab):
        "Creates a continious string with random letters."
        string_length = self.randint(min_length, max_length)
        result_string = ''.join(self.choice(vocabulary) for char in range(string_length))

        return result_string

    def varchar(self, min_length: int = 5, max_length: int = 20):
        """Generates `varchar` type of string."""
        result_string = self.string(min_length, max_length, vocabulary=self.varchar_vocab)

        return result_string

    def text(self, min_length: int = 20, max_length: int = 256):
        """Generates `text` type of string."""
        result_string = self.string(min_length, max_length, vocabulary=self.text_vocab)

        return result_string

    def boolean(self):
        """
        Returns random boolean value.
        """
        result = bool(self.randint(0, 1))
        return result

    def lorem_ipsum(self,
                    min_paragraphs: int = 1,
                    max_paragraphs: int = 5, max_sentences: int = 7, sentence_list: List[str] = sentence_list
                    ):
        """Creates a semi-readable string."""
        paragraphs_amount = self.randint(min_paragraphs, max_paragraphs)

        paragraphs = [*range(paragraphs_amount)]
        for paragraph in paragraphs:
            sentences = [*range(self.randint(1, max_sentences))]

            for sentence in sentences:
                if paragraphs.index(paragraph) == 0 and sentences.index(sentence) == 0:
                    sentences[sentence] = sentence_list[0]
                else:
                    sentences[sentence] = self.choice(sentence_list)

            paragraphs[paragraph] = " ".join(sentences)

        result = "\n".join(paragraphs)

        return result

    def date(self, min_date: datetime = unix_epoch_start) -> datetime:
        """Returns random date."""
        max_date = self.max_date if self.max_date else datetime.now()
        int_delta = int((max_date - min_date).total_seconds())
        random_second = self.randint(0, int_delta)
        random_date = min_date + timedelta(seconds=random_second)
        return random_date
