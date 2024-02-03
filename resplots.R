library(dplyr) 
library(readr) 
library(lubridate)
library(ggplot2)

lat0 <- 61.4646
lon0 <- 29.3949

d <- list.files(path='res', pattern='res-*', full.names=T) %>% read_csv(id="path") %>%
  setNames(c("path", "start", "end", "name", "nimi", "p")) %>%
  mutate(dttm = ymd_hms(stringr::str_extract(path, '\\d{8}_\\d{6}'), tz = 'UTC') + seconds((start+end)/2))

dt <- 600
d2 <- d %>% mutate(day = floor_date(dttm, "day"), clock = dttm - day, 
                   b_clock = floor(as.integer(clock) /dt)/(3600/dt))

# very bare plot
if (F) d2 %>% filter(nimi=="pyrstötiainen" & p>.8) %>% ggplot(aes(x=day, y=b_clock)) + geom_tile(alpha=.2)

llf <- function(x) ifelse(x > 0, x/200, ifelse(x > -6, -.1, ifelse(x > -12, -.2, ifelse(x > -18, -.3, -.4))))


t_grid <- expand.grid(day = seq(min(d2$day), max(d2$day), by="day"),
                      clock = as.difftime(seq(0, 24*60*60, dt), units="secs")) %>%
          mutate(b_clock = floor(as.integer(clock) /dt)/(3600/dt))

t_grid %>% mutate(sun_elev = suncalc::getSunlightPosition(day + clock, lat=lat0, lon=lon0)$altitude,
                  moon_elev = suncalc::getMoonPosition(day + clock, lat=lat0, lon=lon0)$altitude, 
                  moon_frac = suncalc::getMoonIllumination(day + clock)$fraction, 
                  light_level = llf(180 / pi * sun_elev) + 
                                0.02*ifelse(sun_elev>0, 0, moon_frac)*ifelse(moon_elev>0, moon_elev+1, moon_elev)) %>%
  ggplot() + 
  geom_tile(aes(x=day, y=b_clock, fill=light_level)) + scale_fill_gradient(low="#000000", high="#ffffff") +
  geom_tile(aes(x=day, y=b_clock), data=d2 %>% filter(nimi=="lehtopöllö" & p>.9), fill="red", alpha=.2) +
  geom_tile(aes(x=day, y=b_clock), data=d2 %>% filter(nimi=="punatulkku" & p>.9), fill="green", alpha=.2) + 
  geom_tile(aes(x=day, y=b_clock), data=d2 %>% filter(nimi=="talitiainen" & p>.9), fill="blue", alpha=.2) +
  xlab("Calendar day") + ylab("UTC hour") + theme_minimal(12)
  

# datapuutteet näkyviin harmaalla?


# valkoposkihanhi
# urpiainen
# punatulkku
# punarinta
# mustarastas
# (harakka)
# lehtopöllö
# talitiainen
# punakylkirastas
# taviokuurna, kirjosiipikäpylintu
