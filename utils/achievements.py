# THIS FILE CONTAINS SPOILERS!!!
import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from __main__ import Session
from utils.econfuncs import get_bal

bank = "./data/database.sqlite"


# TODO update every callsite to pass sessions explicitly
# until then this will be used as a stop-gap solution
def session_decorator(func):
    async def wrapped(*args, **kwargs):
        session = None
        if not isinstance(args[0], AsyncSession):
            session = Session()
            args = list(args)
            args.insert(0, session)

        try:
            retval = await func(*args, **kwargs)
        except:
            if session is not None:
                await session.rollback()
            raise
        else:
            if session is not None:
                await session.commit()
        finally:
            if session is not None:
                await session.close()

        return retval

    return wrapped


@session_decorator
async def achievement_is_done(
    session, user: discord.User | discord.Member, achievement_name: str
):
    """Check if a user has achieved a specific achievement."""
    achievement = (
        await session.scalars(
            select(models.achievements.User_Achievements).where(
                models.achievements.User_Achievements.user_id == user.id,
                models.achievements.User_Achievements.achievement_id
                == achievement_name,
                models.achievements.User_Achievements.achieved == True,
            )
        )
    ).one_or_none()
    return True if achievement else False


@session_decorator
async def get_achievement_progress(
    session, user: discord.User | discord.Member, achievement_name: str
):
    """Get the progress of a specific achievement for a user."""
    achievement = (
        await session.scalars(
            select(models.achievements.User_Achievements).where(
                models.achievements.User_Achievements.user_id == user.id,
                models.achievements.User_Achievements.achievement_id
                == achievement_name,
            )
        )
    ).one_or_none()

    if not achievement:
        return 0

    return achievement.progress if achievement.progress is not None else 0


@session_decorator
async def complete_achievement(
    session, user: discord.User | discord.Member, achievement_name: str
):
    """Mark an achievement as completed for a user."""
    achievement = (
        await session.scalars(
            select(models.achievements.User_Achievements).where(
                models.achievements.User_Achievements.user_id == user.id,
                models.achievements.User_Achievements.achievement_id
                == achievement_name,
            )
        )
    ).one_or_none()

    if achievement:
        achievement.achieved = True
    else:
        achievement = models.achievements.User_Achievements(
            user_id=user.id,
            achievement_id=achievement_name,
            achieved=True,
            achieved_at=discord.utils.utcnow(),
        )
        session.add(achievement)

    return True


@session_decorator
async def set_achievement_progress(
    session, user: discord.User | discord.Member, achievement_name: str, progress: int
):
    """Set the progress of a specific achievement for a user."""
    achievement = (
        await session.scalars(
            select(models.achievements.User_Achievements).where(
                models.achievements.User_Achievements.user_id == user.id,
                models.achievements.User_Achievements.achievement_id
                == achievement_name,
            )
        )
    ).one_or_none()

    if not achievement:
        achievement = models.achievements.User_Achievements(
            user_id=user.id,
            achievement_id=achievement_name,
            progress=progress,
        )
        session.add(achievement)
    else:
        achievement.progress = progress

    return True


@session_decorator
async def add_achievement_progress(
    session, user: discord.User | discord.Member, achievement_name: str, progress: int
):
    """Add progress to a specific achievement for a user."""
    achievement = (
        await session.scalars(
            select(models.achievements.User_Achievements).where(
                models.achievements.User_Achievements.user_id == user.id,
                models.achievements.User_Achievements.achievement_id
                == achievement_name,
            )
        )
    ).one_or_none()

    if not achievement:
        achievement = models.achievements.User_Achievements(
            user_id=user.id,
            achievement_id=achievement_name,
            progress=progress,
        )
        session.add(achievement)
    else:
        achievement.progress += progress

    return True


class Achievement:
    """Base class for achievements."""

    def __init__(
        self,
        name: str,
        internal_name: str | None = None,
        description: str | None = None,
        progressable: bool = False,
        needed_progress: int = 0,
        hidden: bool = False,
    ):
        self.name = name
        self.internal_name = internal_name or name.lower().replace(" ", "_")
        self.description = description
        self.progressable = progressable
        self.needed_progress = needed_progress
        self.hidden = hidden

    async def is_achieved(self, user: discord.User | discord.Member):
        """Check if the achievement is achieved by the user."""
        return await achievement_is_done(user, self.internal_name)

    async def get_progress(self, user: discord.User | discord.Member):
        """Get the current progress of the achievement for the user."""
        return await get_achievement_progress(user, self.internal_name)

    async def set_progress(self, user: discord.User | discord.Member, progress: int):
        """Set the progress of the achievement for the user."""
        return await set_achievement_progress(user, self.internal_name, progress)

    async def add_progress(self, user: discord.User | discord.Member, progress: int):
        """Add progress to the achievement for the user."""
        return await add_achievement_progress(user, self.internal_name, progress)

    def __str__(self):
        # if self.hidden:
        # return f"**{''.join('?' if c != ' ' else ' ' for c in self.name)}**: {''.join('?' if c != ' ' else ' ' for c in self.description)}"
        return f"**{self.name}**: {self.description}"


class MoneyAchievement(Achievement):
    def __init__(
        self,
        name: str,
        internal_name: str | None = None,
        description: str | None = None,
        needed_progress: int = 0,
        hidden: bool = False,
        **kwargs,
    ):
        super().__init__(
            name=name,
            internal_name=internal_name,
            description=description,
            progressable=True,  # all money achievements are progressable
            needed_progress=needed_progress,
            hidden=hidden,
            **kwargs,
        )

    async def get_progress(self, user: discord.User | discord.Member):
        if not await self.is_achieved(user):
            return await get_bal(user)
        return self.needed_progress

    async def set_progress(self, user: discord.User | discord.Member):
        """Update the progress of the achievement based on the user's balance."""
        current_balance = await get_bal(user)
        current_progress = await get_achievement_progress(user, self.internal_name)
        if current_balance >= self.needed_progress:
            await complete_achievement(user, self.internal_name)
            await set_achievement_progress(
                user, self.internal_name, self.needed_progress
            )
        else:
            if current_balance > current_progress:
                await set_achievement_progress(
                    user, self.internal_name, current_balance
                )


achievements_list = [
    Achievement(
        name="The End?",
        internal_name="the_end",
        description="Reach 2^63-1 $BB",
        hidden=True,
    ),
    Achievement(
        name="Banished",
        description="Overcome your limits.",
        hidden=True,
    ),
    Achievement(
        name="The End.",
        internal_name="the_real_end",
        description="Reach 1 Bougillion $BB",
        hidden=True,
    ),
    Achievement(
        name="Maximum Overdrive",
        description="Get every single upgrade possible.",
        progressable=True,
        needed_progress=7,
        hidden=True,
    ),
    Achievement(
        name="I also like to live dangerously",
        internal_name="austin_powers",
        description="In blackjack, stand on a 5 and lose.",
    ),
    Achievement(
        name="EYE PATCH X-RAY VISION",
        internal_name="x_ray",
        description="In blackjack, double down on 21 and win.",
    ),
    Achievement(
        name="Mr. Generosity",
        internal_name="mr_generosity",
        description="Gift 10 billion $BB to another user.",
    ),
    Achievement(
        name="Mogul Moves", description="Have your balance go into the negatives."
    ),
    Achievement(
        name="Dickhead",
        description="Cause someone to go into the negatives.",
    ),
    Achievement(
        name="Better left than dead",
        description="Lose >=90% of your balance from a single transaction.",
    ),
    Achievement(
        name="Green Fingers",
        description="Have your `,wl` be fully green.",
        progressable=True,
        needed_progress=20,  # this should track highest score
    ),
    Achievement(
        name="Jackpot",
        description="Hit 10x on double or nothing.",
        progressable=True,
        needed_progress=10,
    ),
    Achievement(
        name="Get Fireboarded",
        description="Get your message on the #fireboard.",
    ),
    Achievement(
        name="Frequent Firerer",
        description="Get your message on the #fireboard 5 times.",
        progressable=True,
        needed_progress=5,
    ),
    Achievement(
        name="Firestarter",
        description="Get your message on the #fireboard 10 times.",
        progressable=True,
        needed_progress=10,
    ),
    Achievement(
        name="Expert Cleptomaniac",
        description="Steal the maximum amount of $BB from another user in a single theft.",
        # This has a 1 / 5566.6 chance of happening LOL
    ),
    Achievement(
        name="Cleptomaniac",
        description="Steal from people 100 times.",
        progressable=True,
        needed_progress=100,
    ),
    Achievement(
        name="Petty Thief",
        description="Steal from people 10 times.",
        progressable=True,
        needed_progress=10,
    ),
    Achievement(
        name="I do it for the love of the game",
        description="Steal from someone when your balance is above 1 trillion $BB.",
    ),
    Achievement(
        name="Don't hate the player, hate the game",
        description="Get stolen from 100 times.",
        progressable=True,
        needed_progress=100,
    ),
    Achievement(
        name="Let it Ride!",
        description="Win on a single number in roulette twice in a row.",
    ),
]

money_achievements_list = [
    MoneyAchievement(
        name="Starting Small",
        description="Reach 1 thousand $BB.",
        needed_progress=1_000,
    ),
    MoneyAchievement(
        name="Small Time",
        description="Reach 1 million $BB.",
        needed_progress=1_000_000,
    ),
    MoneyAchievement(
        name="Big Time",
        description="Reach 1 billion $BB.",
        needed_progress=1_000_000_000,
    ),
    MoneyAchievement(
        name="Mega Time",
        description="Reach 1 trillion $BB.",
        needed_progress=1_000_000_000_000,
    ),
    MoneyAchievement(
        name="Giga Time",
        description="Reach 1 quadrillion $BB.",
        needed_progress=1_000_000_000_000_000,
    ),
    MoneyAchievement(
        name="Tera Time",
        description="Reach 1 quintillion $BB.",
        needed_progress=1_000_000_000_000_000_000,
    ),
    MoneyAchievement(
        name="Halfway Point",
        description="Reach 100 quindecillion $BB.",
        needed_progress=1e50,
        hidden=True,
    ),
]
